# -*- coding: utf-8 -*-
"""
GNC Insight - KAP EVREN ÇEKİCİ (hayatta kalma yanlılığı çözümü)

PROBLEM: Geçmişe dönük testte evren "bugün borsada olan şirketler"di. 2021-2025
arasında kotasyondan çıkan, birleşen, konkordatoya giden şirketler veride hiç
yoktu. Bu tek başına test sonuçlarını yukarı çeker — sistem hiç batan şirket
seçmedi, çünkü seçebileceği batan şirket yoktu.

ÇÖZÜM: KAP'ın şirket listesi ucu AKTİF ve PASİF şirketleri ayrı ayrı veriyor.

    GET https://kap.org.tr/tr/api/company/items/{tip}/{durum}
        tip   : IGS = borsa şirketleri, DK = diğer KAP üyeleri
        durum : A = aktif, P = pasif (KOTASYONDAN ÇIKMIŞ)

Ayrıca aktif listede bile "payIslemDurumu" alanı var: "0" ise payı işlem
görmüyor (durdurulmuş / tedbirli / kapatılmış).

ÜÇ ÇIKTI:
  1. kap_evren.json      - anlık kesit: aktif / işlem görmeyen / pasif
  2. kap_evren_gecmis/   - günlük anlık görüntüler (tarih damgalı)
  3. kap_cikanlar.json   - çıkış OLAYLARI: bir kod aktifken pasife düştüğü an

TARİH SORUNU VE DÜRÜST CEVABI:
  KAP bu uçta çıkarılma TARİHİNİ vermiyor. Geçmişe dönük çıkış tarihlerini
  bu uçtan ÜRETEMEYİZ. İki kısmi çözüm var, ikisi de bu dosyada:
    (a) Bugünden itibaren günlük anlık görüntü farkı alarak tarihi biz üretiriz.
    (b) Pasif şirketlerin FİYAT SERİSİ çekilebiliyorsa, serinin bittiği gün
        fiili çıkış tarihidir - geçmiş için EN İYİ yaklaşım budur ve
        kap_fiyat_denemesi() bunu test eder.

DOĞRULANMAMIŞ: Bu dosya, dış ağ erişimi olmayan bir ortamda yazıldı. Uçlar
araştırmayla doğrulandı (IGS/P gerçek veri döndürdüğü test edildi) ama BU KOD
canlı çalıştırılmadı. İlk çalıştırmada --tani bayrağıyla çalıştırın.
"""

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

KLASOR = Path(__file__).parent
PANEL = KLASOR / "gnc-panel"
GECMIS = PANEL / "kap_evren_gecmis"

# www'SUZ adres kullanılmalı - www.kap.org.tr bazı ortamlarda 403 veriyor.
BASE = "https://kap.org.tr/tr/api/company/items"
BASLIK = {
    "User-Agent": "Mozilla/5.0 (compatible; GNCInsightPanel/1.0)",
    "Accept": "application/json",
}
ZAMAN_ASIMI = 30
BEKLE = 0.6          # ~2 istek/sn sınırının altında kal


def cek(tip, durum):
    url = f"{BASE}/{tip}/{durum}"
    r = requests.get(url, headers=BASLIK, timeout=ZAMAN_ASIMI)
    r.raise_for_status()
    d = r.json()
    if not isinstance(d, list):
        raise ValueError(f"{url} beklenen liste yerine {type(d).__name__} döndürdü")
    return d


def kodlari_ayikla(satirlar):
    """
    stockCode alanı virgüllü olabilir: 'ADANA, ADBGR, ADNAC'
    Doner: {KOD: {ad, oid, sermaye}}
    """
    cikti = {}
    for c in satirlar:
        ham = (c.get("stockCode") or "").strip()
        if not ham or ham == "-":
            continue
        for k in ham.replace(" ", "").split(","):
            if k and k != "-":
                cikti[k.upper()] = {
                    "ad": c.get("kapMemberTitle"),
                    "oid": c.get("mkkMemberOid") or c.get("kapMemberOid"),
                    "sermaye": c.get("paidCapital"),
                }
    return cikti


def anlik_gorunutu_al():
    aktif_ham = cek("IGS", "A")
    time.sleep(BEKLE)
    pasif_ham = cek("IGS", "P")

    # payIslemDurumu == "0" -> aktif üye ama payı işlem GÖRMÜYOR
    islem_goren = [c for c in aktif_ham if str(c.get("payIslemDurumu")) == "1"]
    islem_gormeyen = [c for c in aktif_ham if str(c.get("payIslemDurumu")) != "1"]

    return {
        "tarih": datetime.now(timezone.utc).isoformat(),
        "gun": datetime.now(timezone.utc).date().isoformat(),
        "kaynak": f"{BASE}/IGS/{{A,P}}",
        "aktif": kodlari_ayikla(islem_goren),
        "islem_gormeyen": kodlari_ayikla(islem_gormeyen),
        "pasif": kodlari_ayikla(pasif_ham),
        "ham_sayilar": {"aktif_uye": len(aktif_ham), "pasif_uye": len(pasif_ham),
                        "islem_goren": len(islem_goren),
                        "islem_gormeyen": len(islem_gormeyen)},
    }


def cikis_olaylarini_guncelle(yeni):
    """
    Bir önceki anlık görüntüye göre aktiflikten düşen kodları OLAY olarak kaydeder.
    Bu, BUGÜNDEN İTİBAREN gerçek çıkış tarihi üretmenin tek ücretsiz yolu.
    """
    GECMIS.mkdir(parents=True, exist_ok=True)
    onceki_dosyalar = sorted(GECMIS.glob("*.json"))
    olay_yolu = PANEL / "kap_cikanlar.json"
    olaylar = []
    if olay_yolu.exists():
        olaylar = json.loads(olay_yolu.read_text(encoding="utf-8")).get("olaylar", [])

    if onceki_dosyalar:
        eski = json.loads(onceki_dosyalar[-1].read_text(encoding="utf-8"))
        kaybolan = set(eski.get("aktif", {})) - set(yeni["aktif"])
        bilinen = {o["kod"] for o in olaylar}
        for kod in sorted(kaybolan):
            if kod in bilinen:
                continue
            if kod in yeni["pasif"]:
                durum = "pasif (kotasyondan cikti)"
            elif kod in yeni["islem_gormeyen"]:
                durum = "islem gormuyor (durdurulmus)"
            else:
                durum = "bilinmiyor"
            olaylar.append({
                "kod": kod,
                "ad": eski["aktif"][kod]["ad"],
                "tespit_gunu": yeni["gun"],
                "yeni_durum": durum,
                "not": "Tespit gunu, gercek cikis gununden birkac gun sonra olabilir.",
            })

    olay_yolu.write_text(json.dumps({
        "guncelleme": yeni["tarih"],
        "aciklama": ("Aktif listeden dusen kodlar. Gunluk anlik goruntu farkindan uretilir; "
                     "bu dosya SADECE ilk calismadan SONRAKI cikislari yakalar. Daha eski "
                     "cikislar icin pasif listesindeki kodlarin fiyat serisi bitis tarihi "
                     "kullanilmalidir (bkz. kap_fiyat_denemesi)."),
        "olaylar": olaylar,
    }, ensure_ascii=False), encoding="utf-8")
    return olaylar


def fiyat_denemesi(kodlar, ornek=12):
    """
    TANI: Pasif (borsadan cikmis) kodlarin fiyat gecmisi Is Yatirim'dan
    cekilebiliyor mu? Cekilebiliyorsa gecmise donuk hayatta kalma yanliligi
    TAM olarak cozulur - cunku o sirketleri evrene geri koyabiliriz ve
    serinin bittigi gun fiili cikis tarihi olur.
    """
    try:
        from isyatirimhisse import fetch_stock_data
    except ImportError:
        return {"durum": "isyatirimhisse kurulu degil"}
    dene = list(kodlar)[:ornek]
    sonuc = {}
    for k in dene:
        try:
            df = fetch_stock_data(symbols=[k], start_date="01-01-2020", end_date="31-12-2024")
            sonuc[k] = 0 if df is None else len(df)
        except Exception as e:
            sonuc[k] = f"hata: {str(e)[:50]}"
        time.sleep(0.5)
    return sonuc


def cikanlarin_fiyatini_doldur(kodlar, grup=50, paralel=4):
    """
    HAYATTA KALMA YANLILIGININ ASIL COZUMU.
    Borsadan cikmis kodlarin fiyat gecmisini ceker, hisse_gecmis_cikan/
    klasorune yazar. Gecmise donuk test bu klasoru de okur; boylece o
    sirketler EVRENDE olur ve serilerinin bittigi gun fiili cikis tarihidir.

    HIZ: Tek tek cekmek 300 kod icin ~15-25 dk suruyordu. isyatirimhisse
    TOPLU sorguyu destekliyor (mevcut hisse_gecmis_cek.py zaten 50'lik
    gruplar kullaniyor), ustune gruplar PARALEL isleniyor. Yaklasik 10 kat
    hizlanma.

    DEVAM EDEBILIR: Yazilmis dosyalar atlanir, is yarida kalirsa kaldigi
    yerden devam eder.
    """
    from isyatirimhisse import fetch_stock_data

    hedef = PANEL / "hisse_gecmis_cikan"
    hedef.mkdir(parents=True, exist_ok=True)
    kalan = [k for k in sorted(kodlar) if not (hedef / f"{k}.json").exists()]
    zaten = len(kodlar) - len(kalan)
    if zaten:
        print(f"  {zaten} kod zaten cekilmis, atlaniyor")
    if not kalan:
        return zaten, 0, 0

    gruplar = [kalan[i:i + grup] for i in range(0, len(kalan), grup)]
    sayac = {"basarili": zaten, "bos": 0, "hata": 0}
    kilit = threading.Lock()

    def grup_isle(parca):
        try:
            df = fetch_stock_data(symbols=parca, start_date="01-01-2015",
                                  end_date="31-12-2026")
        except Exception as e:
            with kilit:
                sayac["hata"] += len(parca)
            return f"hata: {str(e)[:60]}"
        if df is None or not len(df):
            with kilit:
                sayac["bos"] += len(parca)
            return "bos yanit"

        kol = {str(c).upper(): c for c in df.columns}
        k_kod = kol.get("HGDG_HS_KODU")
        k_kap = kol.get("HGDG_KAPANIS")
        k_tar = kol.get("HGDG_TARIH")
        if not (k_kod and k_kap and k_tar):
            with kilit:
                sayac["hata"] += len(parca)
            return f"beklenen kolonlar yok: {list(df.columns)[:6]}"

        yazilan = 0
        for kod in parca:
            alt = df[df[k_kod] == kod].sort_values(k_tar)
            seri = []
            for _, r in alt.iterrows():
                try:
                    v = float(r[k_kap])
                except (TypeError, ValueError):
                    continue
                t = str(r[k_tar])[:10]
                if len(t) == 10 and v > 0:
                    seri.append({"tarih": t, "kapanis": v})
            if len(seri) < 60:
                with kilit:
                    sayac["bos"] += 1
                continue
            (hedef / f"{kod}.json").write_text(json.dumps({
                "kod": kod, "durum": "borsadan cikmis / islem gormeyen",
                "guncelleme": datetime.now(timezone.utc).isoformat(),
                "gun_sayisi": len(seri),
                "son_islem_gunu": seri[-1]["tarih"],
                "seri": seri,
            }, ensure_ascii=False), encoding="utf-8")
            yazilan += 1
        with kilit:
            sayac["basarili"] += yazilan
        return f"{yazilan}/{len(parca)} yazildi"

    print(f"  {len(kalan)} kod, {len(gruplar)} grup, {paralel} paralel...")
    basla = time.monotonic()
    with ThreadPoolExecutor(max_workers=paralel) as hav:
        isler = {hav.submit(grup_isle, g): i for i, g in enumerate(gruplar, 1)}
        for n, f in enumerate(as_completed(isler), 1):
            sonuc = f.result()
            gecen = time.monotonic() - basla
            print(f"    grup {n}/{len(gruplar)}  {sonuc}  "
                  f"(tahmini kalan {gecen / n * (len(gruplar) - n) / 60:.1f} dk)")

    return sayac["basarili"], sayac["bos"], sayac["hata"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tani", action="store_true",
                    help="Uclari test et, dosya yazma, sadece rapor ver")
    ap.add_argument("--doldur", action="store_true",
                    help="Cikmis sirketlerin fiyat gecmisini cek (UZUN SURER)")
    args = ap.parse_args()

    g = anlik_gorunutu_al()
    print("KAP EVREN")
    print(f"  aktif (payi islem goren) : {len(g['aktif']):>5} kod")
    print(f"  islem gormeyen           : {len(g['islem_gormeyen']):>5} kod")
    print(f"  pasif (kotasyondan cikmis): {len(g['pasif']):>4} kod")
    print(f"  ham uye sayilari         : {g['ham_sayilar']}")

    ornek_pasif = sorted(g["pasif"])[:10]
    print(f"\n  pasif ornekleri: {', '.join(ornek_pasif)}")

    if args.tani:
        print("\nTANI: pasif kodlarin fiyat gecmisi cekilebiliyor mu?")
        r = fiyat_denemesi(g["pasif"])
        for k, v in r.items():
            print(f"  {k:<8} {v}")
        print("\n  → Satir sayisi >0 olanlar evrene GERI KONABILIR.")
        print("    Bu, hayatta kalma yanliligini gecmise donuk olarak cozer.")
        return

    PANEL.mkdir(parents=True, exist_ok=True)
    GECMIS.mkdir(parents=True, exist_ok=True)

    if args.doldur:
        hedefler = set(g["pasif"]) | set(g["islem_gormeyen"])
        print(f"\nCIKMIS/DURDURULMUS {len(hedefler)} kodun fiyat gecmisi cekiliyor...")
        b, bo, h = cikanlarin_fiyatini_doldur(hedefler)
        print(f"  basarili {b} | veri yok {bo} | hata {h}")
        print("  -> gnc-panel/hisse_gecmis_cikan/  (gecmis_test.py bu klasoru de okur)")

    olaylar = cikis_olaylarini_guncelle(g)
    (PANEL / "kap_evren.json").write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    (GECMIS / f"{g['gun']}.json").write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    print(f"\n  kayitli cikis olayi: {len(olaylar)}")
    print(f"  -> gnc-panel/kap_evren.json, kap_cikanlar.json, kap_evren_gecmis/{g['gun']}.json")


if __name__ == "__main__":
    main()
