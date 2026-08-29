# -*- coding: utf-8 -*-
"""
GNC Insight - VBTS TEDBİR ÇEKİCİ (risk katmanının eksik filtresi)

PROBLEM: Taramanın "kanıtı en sağlam katmanı" risk temizliğiydi ama en önemli
filtresi - VBTS tedbiri - verisi olmadığı için çalışmıyordu. Geçmişe dönük
testte de tedbirli hisseler serbestçe alınıp satılabiliyor sayılıyordu; oysa
tek fiyat işlem yöntemine alınmış bir hisse gün içinde normal alınıp satılamaz.

ÇÖZÜM: VBTS kararları KAP'ta yayınlanıyor ve arşiv GERİYE DÖNÜK sorgulanabiliyor.
Her bildirim tedbirin BAŞLANGIÇ ve BİTİŞ tarihini metninde taşıyor. Yani
"2023 Mart'ta X tedbirli miydi?" sorusu bir aralık kontrolüne iniyor.

    POST https://www.kap.org.tr/tr/api/disclosure/members/byCriteria
         {"fromDate":"YYYY-MM-DD","toDate":"YYYY-MM-DD",
          "mkkMemberOidList":[], "subjectList":[]}
    GET  https://www.kap.org.tr/tr/api/notification/attachment-detail/{index}

ÖNEMLİ SINIR - PROXY KULLANILMAYACAK:
  BIST'in VBTS tetikleme EŞİKLERİ kamuya açık değil (beş bağımsız kaynakta
  doğrulandı; yönerge kasten "güçlü emareler" gibi belirsiz ifade kullanıyor).
  Bu yüzden tedbiri fiyat/hacimden TAHMİN ETMEYE ÇALIŞMIYORUZ. Kalibre
  edilemeyen bir tahmin, veri yokluğundan daha tehlikelidir - yanlış bir
  kesinlik hissi verir.

TEDBİR TÜRLERİ (7): brüt takas · kredili işlem yasağı · açığa satış yasağı ·
piyasa emri yasağı · tek fiyat işlem yöntemi · emir paketi · yatırımcı bazlı
kısıtlama. Süreler genelde 15 gün veya 1 ay; üst üste binebilir ve uzatılabilir.

DOĞRULANMAMIŞ: Dış ağ erişimi olmayan bir ortamda yazıldı. Uçlar açık kaynak
dokümantasyondan alındı, canlı test EDİLMEDİ. İlk çalıştırmayı mutlaka
--tani ile yapın; şema farklıysa orada görürsünüz.
"""

import argparse
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

KLASOR = Path(__file__).parent
PANEL = KLASOR / "gnc-panel"
HEDEF = PANEL / "tedbir.json"

SORGU_URL = "https://www.kap.org.tr/tr/api/disclosure/members/byCriteria"
DETAY_URL = "https://www.kap.org.tr/tr/api/notification/attachment-detail/{}"
BASLIK = {
    "User-Agent": "Mozilla/5.0 (compatible; GNCInsightPanel/1.0)",
    "Accept": "application/json",
    "Content-Type": "application/json",
}
ZAMAN_ASIMI = 40
PARALEL = 4                   # es zamanli detay istegi
ISTEK_HIZI = 4.0              # saniyede en fazla kac istek (TUM is parcaciklari toplam)
ARA_KAYIT = KLASOR / "gnc-panel" / "tedbir_ara"   # yarim kalirsa buradan devam

VBTS_DESEN = re.compile(r"VBTS|VOLAT[İI]L[İI]TE\s+BAZLI\s+TEDB[İI]R", re.IGNORECASE)
TARIH_DESEN = re.compile(r"(\d{2})[.\-/](\d{2})[.\-/](\d{4})")
# Hisse kodu: 4-6 buyuk harf, istege bagli .E / .F soneki
KOD_DESEN = re.compile(r"\b([A-ZÇĞİÖŞÜ]{4,6})(?:\.[EFVM])?\b")

TEDBIR_TURLERI = {
    "brüt takas": "brut_takas",
    "kredili": "kredi_yasagi",
    "açığa satış": "aciga_satis_yasagi",
    "piyasa emri": "piyasa_emri_yasagi",
    "tek fiyat": "tek_fiyat",
    "emir paketi": "emir_paketi",
    "emir iptali": "emir_paketi",
    "yatırımcı bazlı": "yatirimci_bazli",
}

# Hisse kodu SANILABILECEK ama kod OLMAYAN kelimeler
YASAK = {"VBTS", "BORSA", "PIYASA", "PAZAR", "TEDBIR", "ISTANBUL", "SISTEM",
         "KURUL", "SERMAYE", "YATIRIM", "GENEL", "MUDURLUK", "KARAR", "PAYLARI",
         "PAYLARIN", "ISLEM", "TARIHLERI", "ARASINDA", "UYGULANACAK", "SIRKET",
         "ANONIM", "MENKUL", "DEGERLER", "BILDIRIM", "ACIKLAMA", "KAPSAMINDA"}


class HizSinirlayici:
    """
    TUM is parcaciklari icin ORTAK hiz siniri. Paralel calisirken her is
    parcaciginin ayri ayri beklemesi yetmez - toplam hiz sinirlanmali,
    yoksa KAP 429 doner ve tum dolum coker.
    """

    def __init__(self, saniyede):
        self.aralik = 1.0 / saniyede
        self.kilit = threading.Lock()
        self.son = 0.0

    def bekle(self):
        with self.kilit:
            simdi = time.monotonic()
            gecikme = self.son + self.aralik - simdi
            if gecikme > 0:
                time.sleep(gecikme)
                simdi = time.monotonic()
            self.son = simdi


HIZ = HizSinirlayici(ISTEK_HIZI)


def _oturum():
    s = requests.Session()
    s.headers.update(BASLIK)
    # tek TCP baglantisi yerine havuz - paralel istekte tikanmasin
    a = requests.adapters.HTTPAdapter(pool_connections=PARALEL + 2,
                                      pool_maxsize=PARALEL + 2)
    s.mount("https://", a)
    return s


def bildirimleri_sorgula(s, bas, bit):
    """Bir tarih penceresindeki bildirimler. Yanit 2000 kayitla sinirli."""
    gövde = {"fromDate": bas, "toDate": bit, "mkkMemberOidList": [], "subjectList": []}
    for deneme in range(4):
        HIZ.bekle()
        r = s.post(SORGU_URL, json=gövde, timeout=ZAMAN_ASIMI)
        if r.status_code == 429:
            time.sleep(5 * (deneme + 1))     # geri cekil ve tekrar dene
            continue
        break
    r.raise_for_status()
    d = r.json()
    if isinstance(d, dict):                    # sema varyasyonuna tolerans
        for anahtar in ("content", "data", "result", "disclosures"):
            if isinstance(d.get(anahtar), list):
                return d[anahtar]
        return []
    return d if isinstance(d, list) else []


def vbts_mi(kayit):
    metin = " ".join(str(kayit.get(k, "")) for k in
                     ("title", "summary", "subject", "basicInfo", "disclosureClass"))
    return bool(VBTS_DESEN.search(metin))


def detay_al(s, index):
    for deneme in range(4):
        HIZ.bekle()
        r = s.get(DETAY_URL.format(index), timeout=ZAMAN_ASIMI)
        if r.status_code == 429:
            time.sleep(5 * (deneme + 1))
            continue
        break
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        return {"_ham": r.text}


def metni_cikar(detay):
    if isinstance(detay, str):
        return detay
    parcalar = []
    def gez(o):
        if isinstance(o, str):
            parcalar.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                gez(v)
        elif isinstance(o, list):
            for v in o:
                gez(v)
    gez(detay)
    return " ".join(parcalar)


def ayristir(metin, bildirim_tarihi=None):
    """
    Metinden (kodlar, tedbir_turleri, baslangic, bitis) cikarir.
    Tarih bulunamazsa bildirim tarihi + 30 gun VARSAYILMAZ - None doner.
    Tahmin uretmek, veri yoklugundan daha tehlikelidir.
    """
    tarihler = []
    for g, a, y in TARIH_DESEN.findall(metin):
        try:
            tarihler.append(date(int(y), int(a), int(g)))
        except ValueError:
            continue
    tarihler = sorted(set(tarihler))
    bas = bit = None
    if len(tarihler) >= 2:
        bas, bit = tarihler[0], tarihler[-1]
    elif len(tarihler) == 1:
        bas = tarihler[0]

    dusuk = metin.lower()
    turler = sorted({v for k, v in TEDBIR_TURLERI.items() if k in dusuk})

    kodlar = sorted({k for k in KOD_DESEN.findall(metin.upper())
                     if k not in YASAK and not k.isdigit()})
    return kodlar, turler, bas, bit


def pencereler(bas, bit, gun=30):
    t = bas
    while t < bit:
        s = min(t + timedelta(days=gun), bit)
        yield t.isoformat(), s.isoformat()
        t = s + timedelta(days=1)


def _pencere_isle(s, a, b, tani):
    """Tek pencereyi isler. Detay istekleri PARALEL, hiz siniri ORTAK."""
    hepsi = bildirimleri_sorgula(s, a, b)
    adaylar = [k for k in hepsi if vbts_mi(k)]
    sinir = len(hepsi) >= 1990
    if tani and adaylar:
        return hepsi, adaylar, [], sinir

    def bir(k):
        ix = k.get("disclosureIndex") or k.get("index") or k.get("id")
        if not ix:
            return None
        try:
            metin = metni_cikar(detay_al(s, ix))
        except Exception:
            metin = " ".join(str(v) for v in k.values())
        kodlar, turler, t0, t1 = ayristir(metin, k.get("publishDate"))
        return {"index": ix,
                "bildirim_tarihi": k.get("publishDate") or k.get("date"),
                "kodlar": kodlar, "turler": turler,
                "baslangic": t0.isoformat() if t0 else None,
                "bitis": t1.isoformat() if t1 else None,
                "eksik": (not kodlar) or (not t0)}

    kayitlar = []
    if adaylar:
        with ThreadPoolExecutor(max_workers=PARALEL) as hav:
            for f in as_completed([hav.submit(bir, k) for k in adaylar]):
                r = f.result()
                if r:
                    kayitlar.append(r)
    return hepsi, adaylar, kayitlar, sinir


def topla(bas, bit, tani=False):
    """
    DEVAM EDEBILIR. Her pencere bittiginde sonucu tedbir_ara/ altina yazar.
    GitHub Actions zaman asimina ugrarsa ya da baglanti koparsa, ikinci
    calistirmada TAMAMLANMIS pencereler atlanir ve kaldigi yerden devam eder.
    3 saatlik bir isi bastan baslatmak kabul edilemez.
    """
    s = _oturum()
    ARA_KAYIT.mkdir(parents=True, exist_ok=True)
    kayitlar, hata = [], 0
    pencere_listesi = list(pencereler(bas, bit))
    basla = time.monotonic()

    for i, (a, b) in enumerate(pencere_listesi, 1):
        ara = ARA_KAYIT / f"{a}_{b}.json"
        if ara.exists() and not tani:
            kayitlar.extend(json.loads(ara.read_text(encoding="utf-8")))
            print(f"  [{i}/{len(pencere_listesi)}] {a}..{b}  (onceden tamamlanmis, atlandi)")
            continue
        try:
            hepsi, adaylar, yeni, sinir = _pencere_isle(s, a, b, tani)
        except Exception as e:
            hata += 1
            print(f"  [{i}/{len(pencere_listesi)}] {a}..{b} HATA: {str(e)[:70]}")
            time.sleep(3)
            continue

        if tani and adaylar:
            print("\n  ORNEK KAYIT ALANLARI:", list(adaylar[0].keys())[:14])
            print("  ORNEK:", json.dumps(adaylar[0], ensure_ascii=False)[:500])
            return kayitlar, hata

        ara.write_text(json.dumps(yeni, ensure_ascii=False), encoding="utf-8")
        kayitlar.extend(yeni)
        gecen = time.monotonic() - basla
        kalan = gecen / i * (len(pencere_listesi) - i)
        print(f"  [{i}/{len(pencere_listesi)}] {a}..{b}  bildirim {len(hepsi):>5} | "
              f"VBTS {len(adaylar):>3} | tahmini kalan {kalan/60:>5.1f} dk"
              + ("  ← 2000 SINIRI" if sinir else ""))
    return kayitlar, hata


def araliga_cevir(kayitlar):
    """{KOD: [{baslangic, bitis, turler}]} - tarama ve test bunu okur."""
    ix = {}
    for k in kayitlar:
        if k["eksik"] or not k["baslangic"]:
            continue
        for kod in k["kodlar"]:
            ix.setdefault(kod, []).append({
                "baslangic": k["baslangic"],
                "bitis": k["bitis"] or k["baslangic"],
                "turler": k["turler"],
            })
    for kod in ix:
        ix[kod].sort(key=lambda x: x["baslangic"])
    return ix


def tedbirli_mi(ix, kod, gun):
    """Bir kod belirli bir gunde tedbirli miydi? Tarama ve test bunu cagirir."""
    for a in ix.get(kod, []):
        if a["baslangic"] <= gun <= a["bitis"]:
            return a["turler"] or True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bas", default="2021-01-01")
    ap.add_argument("--bit", default=date.today().isoformat())
    ap.add_argument("--tani", action="store_true",
                    help="Tek pencere calistir, ham sema goster, dosya yazma")
    ap.add_argument("--gunluk", action="store_true",
                    help="Sadece son 5 gunu cek ve mevcut dosyaya EKLE")
    args = ap.parse_args()

    if args.gunluk:
        args.bas = (date.today() - timedelta(days=5)).isoformat()
        args.bit = date.today().isoformat()
    if args.tani:
        args.bit = (date.fromisoformat(args.bas) + timedelta(days=30)).isoformat()

    print(f"VBTS TEDBIR CEKIMI  {args.bas} .. {args.bit}")
    sonuc = topla(date.fromisoformat(args.bas), date.fromisoformat(args.bit), args.tani)
    if args.tani:
        print("\nTANI bitti. Sema yukarida. Uygunsa --tani olmadan calistirin.")
        return
    kayitlar, hata = sonuc

    mevcut = []
    if HEDEF.exists() and args.gunluk:
        mevcut = json.loads(HEDEF.read_text(encoding="utf-8")).get("kayitlar", [])
    bilinen = {k["index"] for k in mevcut}
    yeni = [k for k in kayitlar if k["index"] not in bilinen]
    hepsi = mevcut + yeni

    ix = araliga_cevir(hepsi)
    eksik = sum(1 for k in hepsi if k["eksik"])
    PANEL.mkdir(parents=True, exist_ok=True)
    HEDEF.write_text(json.dumps({
        "guncelleme": datetime.now(timezone.utc).isoformat(),
        "kaynak": "KAP bildirim arsivi (VBTS)",
        "aralik": {"bas": args.bas, "bit": args.bit},
        "kayit_sayisi": len(hepsi),
        "yeni_kayit": len(yeni),
        "ayristirilamayan": eksik,
        "sorgu_hatasi": hata,
        "not": ("Tedbir esikleri BIST tarafindan aciklanmadigi icin tedbir "
                "fiyat/hacimden TAHMIN EDILMEZ. Burada sadece KAP'ta ilan "
                "edilmis GERCEK tedbirler vardir."),
        "kayitlar": hepsi,
        "kod_araliklari": ix,
    }, ensure_ascii=False), encoding="utf-8")

    print(f"\n  toplam kayit  : {len(hepsi)} (yeni {len(yeni)})")
    print(f"  ayristirilamayan: {eksik}")
    print(f"  tedbir goren kod: {len(ix)}")
    if ix:
        ornek = sorted(ix.items(), key=lambda x: -len(x[1]))[:6]
        for k, v in ornek:
            print(f"    {k:<7} {len(v):>3} tedbir dönemi  ilk: {v[0]['baslangic']}")
    print(f"  -> gnc-panel/tedbir.json")


if __name__ == "__main__":
    main()
