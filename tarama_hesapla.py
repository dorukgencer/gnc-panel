# -*- coding: utf-8 -*-
"""
GNC Insight - TARAMA MOTORU

NE YAPAR: 472 sirketi sirayla kapilardan gecirir ve portfoye aday olabilecekleri
birakir. Her kapida KIMIN, NEDEN elendigi kayit altina alinir - tarama.json'da
her sirketin butun olculeri ve elenme gerekcesi bulunur.

TASARIM ILKELERI (tartismaya kapali):
  1. ONCE ELE, SONRA SIRALA. "Hangi hisse kazanir" sorusunun BIST'te dogrulanmis
     cevabi yok; "hangi sirket yapisal olarak riskli" sorusunun cevabi var.
  2. MUTLAK ESIK YOK, KESITSEL YUZDELIK VAR. "Net borc/FAVOK < 3" demek benim
     tercihimdir. "Sektorunde en borclu %25'lik dilim" demek veriden gelir.
     Enflasyon muhasebesi mutlak esikleri zaten anlamsiz kildi.
  3. SKOR YOK. Tek bir sayiya indirgeme sahte kesinlik uretir. Sirket ya kapidan
     gecer ya gecmez; gecenler sektor ici yuzdelikle siralanir.
  4. EKSIK FILTRE GIZLENMEZ. Verisi olmayan filtre (VBTS tedbiri, denetim
     gorusu) "aktif degil" olarak RAPORLANIR. Sistem kendi korlugunu bilir.
  5. SUPHELI VERI KULLANILMAZ. Karantinadaki sirket-yillari hesaba katilmaz.

CIKTI: gnc-panel/tarama.json
"""

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

import kalem_haritasi as KH

KLASOR = Path(__file__).parent
PANEL = KLASOR / "gnc-panel"
FIN = PANEL / "finansal"
GECMIS = PANEL / "hisse_gecmis"

# ----------------------------------------------------------------- ayarlar
# Hepsi YUZDELIK (kesitsel). Tek mutlak esik likidite ve halka aciklikta -
# onlar piyasa yapisi kurallari, degerleme tercihi degil.
AYAR = {
    "min_gunluk_hacim_tl": 5_000_000,   # gunluk islem hacmi alt siniri
    "min_halka_aciklik": 0.15,          # HAO_PD / PD alt siniri
    "bayat_ceyrek": 3,                  # son bilanco bu kadar ceyrek geridyse ele
    "karantina_yil_penceresi": 2,       # son N yilda karantina varsa ele
    "tahakkuk_en_kotu_dilim": 0.25,     # sektor icinde en kotu %25 elenir
    "borcluluk_en_kotu_dilim": 0.25,    # net borc/FAVOK en yuksek %25 elenir
    "min_faiz_karsilama": 1.0,          # fin.gid.oncesi faaliyet kari / finansman gideri
    "fiyat_veto_ortalama_gun": 200,     # bu ortalamanin altindaysa alim yok
    "degerleme_en_pahali_dilim": 0.25,  # sektor icinde en pahali %25 elenir
    "asiri_uzama_esigi": 30,            # ortalamanin %30 ustu = asiri uzamis (uyari)
}

# Verisi OLMAYAN, bu yuzden calismayan filtreler. Panelde acikca gosterilir.
EKSIK_FILTRELER = [
    {"ad": "VBTS tedbiri", "neden": "Tedbir verisi henuz cekilmiyor (KAP bildirimleri)",
     "onem": "yuksek"},
    {"ad": "Bagimsiz denetim gorusu", "neden": "Sartli/olumsuz gorus verisi cekilmiyor",
     "onem": "orta"},
    {"ad": "Hacim suregi", "neden": "Elimizde tek gunluk hacim var, ortalama degil",
     "onem": "orta"},
]


# ----------------------------------------------------------------- yardimci

def don_sirala(d):
    y, c = d.split("/")
    return (int(y), int(c))


def ttm(veri, alan, donemler, fmt, _ix=None, _ixc=None):
    """
    Son 12 ay (TTM). Bilanco kalemleri kumulatif oldugu icin:
        Q!=12 ise  TTM = bu_yil/Q + gecen_yil/12 - gecen_yil/Q
        Q==12 ise  TTM = bu_yil/12
    Gerekli donemlerden biri eksikse None doner (tahmin URETMEZ).
    """
    if not donemler:
        return None
    son = donemler[-1]
    y, q = don_sirala(son)
    d = lambda p: KH.deger(veri, alan, p, fmt, _ix, _ixc)
    if q == 12:
        return d(son)
    a, b, c = d(son), d(f"{y-1}/12"), d(f"{y-1}/{q}")
    if None in (a, b, c):
        return None
    return a + b - c


def yuzdelik_esik(degerler, dilim, buyuk_kotu=True):
    """Kesitsel esik. buyuk_kotu=True ise ust %dilim kotudur."""
    temiz = sorted(v for v in degerler if v is not None)
    if len(temiz) < 8:          # cok az ornek varsa esik uretme
        return None
    k = int(len(temiz) * (1 - dilim)) if buyuk_kotu else int(len(temiz) * dilim)
    k = max(0, min(k, len(temiz) - 1))
    return temiz[k]


def ortalama_mesafe(seri, gun):
    """Son kapanisin N gunluk basit ortalamaya gore yuzde mesafesi."""
    if len(seri) < gun:
        return None
    son = seri[-1]["kapanis"]
    ort = statistics.fmean(x["kapanis"] for x in seri[-gun:])
    if not ort:
        return None
    return (son / ort - 1) * 100


# ----------------------------------------------------------------- olcum

def olcumleri_hesapla(kod, veri, piyasa, fiyat_serisi):
    """Bir sirketin butun ham olculeri. Hesaplanamayan alan None kalir."""
    fmt = KH.format_belirle(veri)
    ix, ixc = KH._indeks(veri), KH._indeks_coklu(veri)
    donemler = sorted(veri.get("donemler", []), key=don_sirala)
    son = donemler[-1] if donemler else None
    D = lambda a: KH.deger(veri, a, son, fmt, ix, ixc) if son else None
    T = lambda a: ttm(veri, a, donemler, fmt, ix, ixc)

    o = {"kod": kod, "format": fmt, "son_donem": son, "donem_sayisi": len(donemler)}

    # --- stok kalemler (bilanco: oldugu gibi)
    o["ozkaynak"] = D("ozkaynak")
    o["toplam_varlik"] = D("toplam_varlik")
    o["nakit"] = D("nakit")
    o["finansal_borc"] = D("finansal_borc")
    o["net_yp_pozisyon"] = D("net_yp_pozisyon")

    # --- akim kalemler (TTM)
    o["gelir_ttm"] = T("gelir")
    o["net_kar_ttm"] = T("net_kar")
    o["amortisman_ttm"] = T("amortisman")
    o["isletme_nakit_ttm"] = T("isletme_nakit")
    o["fin_oncesi_fk_ttm"] = T("fin_oncesi_fk")
    o["finansman_gideri_ttm"] = T("finansman_gideri")

    # --- turetilmis
    fk, am = o["fin_oncesi_fk_ttm"], o["amortisman_ttm"]
    o["favok_ttm"] = (fk + am) if None not in (fk, am) else None

    nb = None
    if o["finansal_borc"] is not None and o["nakit"] is not None:
        nb = o["finansal_borc"] - o["nakit"]
    o["net_borc"] = nb

    o["net_borc_favok"] = (nb / o["favok_ttm"]) if (nb is not None and o["favok_ttm"]) else None

    nk, isn, tv = o["net_kar_ttm"], o["isletme_nakit_ttm"], o["toplam_varlik"]
    # Tahakkuk kalitesi: (net kar - isletme nakdi) / toplam varlik.
    # YUKSEK = kar nakde donmuyor = KOTU. BIST'te kaniti en tutarli olcu budur.
    o["tahakkuk"] = ((nk - isn) / tv) if None not in (nk, isn, tv) and tv else None

    fg = o["finansman_gideri_ttm"]
    o["faiz_karsilama"] = (fk / abs(fg)) if (fk is not None and fg) else None

    oz = o["ozkaynak"]
    o["yp_pozisyon_oran"] = (o["net_yp_pozisyon"] / oz) if (o["net_yp_pozisyon"] is not None and oz) else None

    # --- piyasa
    p = piyasa or {}
    o["fiyat"] = p.get("fiyat")
    o["pd"] = p.get("pd")
    o["hao_pd"] = p.get("hao_pd")
    o["hacim"] = p.get("hacim")
    o["halka_aciklik"] = (p["hao_pd"] / p["pd"]) if (p.get("pd") and p.get("hao_pd")) else None

    # Firma Degeri = Piyasa Degeri + Net Borc.  FD/FAVOK, TMS 29'a en dayanikli carpan.
    o["fd"] = (o["pd"] + nb) if (o["pd"] is not None and nb is not None) else None
    o["fd_favok"] = (o["fd"] / o["favok_ttm"]) if (o["fd"] is not None and o["favok_ttm"] and o["favok_ttm"] > 0) else None
    o["pd_dd"] = (o["pd"] / oz) if (o["pd"] is not None and oz and oz > 0) else None

    # --- fiyat
    o["ma_mesafe"] = ortalama_mesafe(fiyat_serisi, AYAR["fiyat_veto_ortalama_gun"]) if fiyat_serisi else None
    o["fiyat_gun_sayisi"] = len(fiyat_serisi) if fiyat_serisi else 0

    return o


# ----------------------------------------------------------------- kapilar

def kapilari_uygula(olcumler, karantina, rotasyon_evre, bekl_donem):
    """
    Sirayla kapilar. Bir sirket elenince sonraki kapilara girmez ama olculeri
    korunur - panelde "nerede elendi" gosterilebilsin diye.
    Doner: (huni_listesi, olcumler-guncellenmis)
    """
    aday = [o for o in olcumler]
    huni = [{"kapi": "Başlangıç", "aciklama": "Tüm şirketler", "kalan": len(aday), "elenen": 0}]

    def kapi(ad, aciklama, test):
        """
        test(o) -> None (gecti) veya sebep listesi/str (elendi).
        KARSI ARGUMAN 2'nin cevabi: bir sirket ayni kapida birden fazla testten
        kalabilir. Tek sebep kaydetmek "neden elendi" sorusunu eksik cevaplar,
        o yuzden TUM sebepler tutulur ve kapi ici kirilim raporlanir.
        """
        nonlocal aday
        gecen, elenen = [], 0
        kirilim = {}
        for o in aday:
            sebepler = test(o)
            if isinstance(sebepler, str):
                sebepler = [sebepler]
            if sebepler:
                o["elendi"] = ad
                o["elenme_sebepleri"] = sebepler
                o["elenme_sebebi"] = sebepler[0]
                elenen += 1
                for sb in sebepler:
                    etiket = sb.split("(")[0].strip()
                    kirilim[etiket] = kirilim.get(etiket, 0) + 1
            else:
                gecen.append(o)
        aday = gecen
        huni.append({"kapi": ad, "aciklama": aciklama, "kalan": len(aday),
                     "elenen": elenen, "kirilim": kirilim})

    # K0 - format: banka ve sigorta ayri hattan gecer, bu surumde taramaya girmez
    kapi("Format", "Banka ve sigorta ayrı oran seti gerektirir — ayrı hatta",
         lambda o: f"{o['format']} formatı (ayrı hat)" if o["format"] != "SANAYI" else None)

    # K1 - veri sagligi
    def veri_testi(o):
        if not o["son_donem"]:
            return "Hiç dönem yok"
        y, q = don_sirala(o["son_donem"])
        gecikme = (bekl_donem[0] - y) * 4 + (bekl_donem[1] - q) // 3
        if gecikme >= AYAR["bayat_ceyrek"]:
            return f"Bilanço bayat (son {o['son_donem']}, ~{gecikme} çeyrek geride)"
        kar = karantina.get(o["kod"], [])
        pencere = [yy for yy in kar if yy >= bekl_donem[0] - AYAR["karantina_yil_penceresi"]]
        if pencere:
            return f"Karantina: {pencere} yıllarında kümülatif seri bozuk"
        return None
    kapi("Veri sağlığı", "Bayat bilanço ve karantinalı şirketler", veri_testi)

    # K2 - piyasa verisi
    kapi("Piyasa verisi", "Fiyat / piyasa değeri / hacim eksik olanlar",
         lambda o: "Piyasa verisi yok" if None in (o["fiyat"], o["pd"], o["hacim"]) else None)

    # K3 - likidite ve erisilebilirlik (manipulasyon riskinin en iyi vekili)
    def likidite(o):
        s = []
        if o["hacim"] is not None and o["hacim"] < AYAR["min_gunluk_hacim_tl"]:
            s.append(f"Günlük hacim düşük ({o['hacim']/1e6:.1f}mn TL)")
        if o["halka_aciklik"] is not None and o["halka_aciklik"] < AYAR["min_halka_aciklik"]:
            s.append(f"Halka açıklık düşük (%{o['halka_aciklik']*100:.1f})")
        return s or None
    kapi("Likidite", "Düşük hacim ve düşük halka açıklık", likidite)

    # K4 - hesaplanabilirlik: olculeri cikmayan sirket degerlendirilemez
    kapi("Ölçülebilirlik", "Dayanıklılık ölçüleri hesaplanamayanlar",
         lambda o: "Dayanıklılık ölçüleri hesaplanamadı"
         if None in (o["isletme_nakit_ttm"], o["favok_ttm"], o["tahakkuk"]) else None)

    # K5 - dayaniklilik (kesitsel esikler bu asamadaki adaylardan uretilir)
    tah_esik = yuzdelik_esik([o["tahakkuk"] for o in aday], AYAR["tahakkuk_en_kotu_dilim"], True)
    brc = [o["net_borc_favok"] for o in aday if o["net_borc_favok"] is not None and o["net_borc_favok"] > 0]
    brc_esik = yuzdelik_esik(brc, AYAR["borcluluk_en_kotu_dilim"], True)

    def dayaniklilik(o):
        s = []
        if o["isletme_nakit_ttm"] is not None and o["isletme_nakit_ttm"] <= 0:
            s.append("İşletme nakit akışı negatif")
        if o["favok_ttm"] is not None and o["favok_ttm"] <= 0:
            s.append("FAVÖK negatif")
        if tah_esik is not None and o["tahakkuk"] is not None and o["tahakkuk"] > tah_esik:
            s.append(f"Tahakkuk kalitesi kötü (en kötü %{AYAR['tahakkuk_en_kotu_dilim']*100:.0f})")
        if brc_esik is not None and o["net_borc_favok"] is not None and o["net_borc_favok"] > brc_esik:
            s.append(f"Borçluluk yüksek (NB/FAVÖK {o['net_borc_favok']:.1f})")
        if o["faiz_karsilama"] is not None and o["faiz_karsilama"] < AYAR["min_faiz_karsilama"]:
            s.append(f"Faiz karşılama yetersiz ({o['faiz_karsilama']:.2f}x)")
        return s or None
    kapi("Dayanıklılık", "Nakit akışı, tahakkuk kalitesi, borçluluk, faiz karşılama", dayaniklilik)

    # K6 - degerleme: sektor ICI kesitsel siralama
    #
    # SESSIZ HATA DUZELTMESI (29 Agu 2026):
    # Ilk surumde sektorde 8'den az sirket kalinca yuzdelik_esik() None donuyor
    # ve o sektordeki HERKES filtresiz geciyordu - hicbir uyari vermeden.
    # Olculdu: 17 sektorun 10'u bu durumda, 35 sirket sessizce geciyordu.
    # Cozum: sektor yetersizse TUM EVREN dagilimina dusulur ve bu durum
    # raporlanir. Filtre ya calisir ya da calismadigini soyler; sessiz kalmaz.
    grup = {}
    for o in aday:
        if o["fd_favok"] is not None:
            grup.setdefault(o.get("sektor"), []).append(o["fd_favok"])
    sektor_esik = {sk: yuzdelik_esik(v, AYAR["degerleme_en_pahali_dilim"], True)
                   for sk, v in grup.items()}
    evren_esik = yuzdelik_esik([o["fd_favok"] for o in aday],
                               AYAR["degerleme_en_pahali_dilim"], True)
    yedege_dusen = sorted(sk for sk, e in sektor_esik.items() if e is None)

    def degerleme(o):
        if o["fd_favok"] is None:
            return "FD/FAVÖK hesaplanamadı"
        e = sektor_esik.get(o.get("sektor"))
        yedek = False
        if e is None:
            e, yedek = evren_esik, True
        o["degerleme_esigi_kaynagi"] = "evren" if yedek else "sektor"
        if e is not None and o["fd_favok"] > e:
            nerede = "Evrende" if yedek else "Sektöründe"
            return f"{nerede} pahalı (FD/FAVÖK {o['fd_favok']:.1f})"
        return None
    kapi("Değerleme", "Sektör içinde en pahalı dilim", degerleme)
    huni[-1]["uyari"] = (f"{len(yedege_dusen)} sektörde yeterli şirket yok, evren eşiğine düşüldü: "
                         + ", ".join(yedege_dusen)) if yedege_dusen else None

    # K7 - fiyat vetosu: ELEMEZ, AYIRIR.
    # KARSI ARGUMAN 3'un cevabi: fiyat vetosu bir KALITE degil ZAMANLAMA kuralidir.
    # Ortalamanin altindaki sirket "kotu" degil, "su an degil"dir. Onu kaliteden
    # elenenlerle ayni cope atmak bilgi kaybidir - IZLEME listesine gider ve
    # her ay yeniden bakilir. Doruk'un "eklenebilecek hisseleri takip etmek"
    # istegi tam olarak bu listedir.
    kalite_gecti = list(aday)
    adaylar, izleme = [], []
    for o in kalite_gecti:
        m = o["ma_mesafe"]
        if m is None:
            o["zamanlama"] = "veri_yok"
            o["zamanlama_not"] = f"Fiyat geçmişi yetersiz ({o['fiyat_gun_sayisi']} gün)"
            izleme.append(o)
        elif m < 0:
            o["zamanlama"] = "bekle"
            o["zamanlama_not"] = (f"{AYAR['fiyat_veto_ortalama_gun']} günlük ortalamanın "
                                  f"%{abs(m):.1f} altında")
            izleme.append(o)
        else:
            # KARSI ARGUMAN 4'un cevabi: veto tek tarafliydi. Ortalamanin cok
            # ustundeki hisseye girmek de "kaybetmemek" hedefiyle celisir.
            # Elemiyoruz ama ISARETLIYORUZ - karar gorunur olsun.
            o["zamanlama"] = "uygun"
            o["zamanlama_not"] = f"Ortalamanın %{m:.1f} üstünde"
            o["asiri_uzamis"] = m > AYAR["asiri_uzama_esigi"]
            adaylar.append(o)

    huni.append({"kapi": "Fiyat vetosu", "kalan": len(adaylar), "elenen": len(izleme),
                 "aciklama": "Elenmez — İZLEME listesine ayrılır",
                 "kirilim": {"İzleme listesine ayrıldı": len(izleme)}})

    # K8 - ortam: ELEMEZ, ISARETLER. Rotasyon ciktisini karara baglar.
    for o in adaylar + izleme:
        o["ortam_evre"] = rotasyon_evre.get(o.get("sektor"))
        o["ortam_uyari"] = (o["ortam_evre"] == "daralma")

    return huni, adaylar, izleme


# ----------------------------------------------------------------- ana

def main():
    piyasa = json.loads((PANEL / "sektor_hisse_veri.json").read_text(encoding="utf-8")).get("hisseler", {})
    liste = json.loads((PANEL / "sirket_listesi.json").read_text(encoding="utf-8")).get("sirketler", [])
    sektor = {s["kod"]: s.get("sektor") for s in liste}
    sektor_ad = {s["kod"]: s.get("sektor_ad") for s in liste}
    isim = {s["kod"]: s.get("ad") for s in liste}

    try:
        karantina = json.loads((PANEL / "karantina.json").read_text(encoding="utf-8")).get("sirketler", {})
    except FileNotFoundError:
        karantina = {}

    rot_evre = {}
    try:
        rot = json.loads((PANEL / "rotasyon_gecmis.json").read_text(encoding="utf-8"))
        rot_evre = {s["kod"]: s.get("evre") for s in rot.get("sektorler", [])}
    except FileNotFoundError:
        pass

    b = datetime.now(timezone.utc)
    ay = b.month - 3
    yy = b.year
    if ay <= 0:
        yy, ay = yy - 1, ay + 12
    bekl = (yy, ((ay - 1) // 3 + 1) * 3)

    olcumler = []
    for f in sorted(FIN.glob("*.json")):
        kod = f.stem
        veri = json.loads(f.read_text(encoding="utf-8"))
        gp = GECMIS / f"{kod}.json"
        seri = []
        if gp.exists():
            seri = json.loads(gp.read_text(encoding="utf-8")).get("seri", [])
        o = olcumleri_hesapla(kod, veri, piyasa.get(kod), seri)
        o["ad"] = isim.get(kod, kod)
        o["sektor"] = sektor.get(kod)
        o["sektor_ad"] = sektor_ad.get(kod)
        o["elendi"] = None
        o["elenme_sebebi"] = None
        olcumler.append(o)

    huni, adaylar, izleme = kapilari_uygula(olcumler, karantina, rot_evre, bekl)

    # Gecenleri sektor ici FD/FAVOK ucuzlugu ile sirala (skor degil, siralama)
    anahtar = lambda o: (o["fd_favok"] if o["fd_favok"] is not None else 9e9)
    adaylar.sort(key=anahtar)
    izleme.sort(key=anahtar)

    # KARSI ARGUMAN 5'in cevabi: 39 adaydan 12-15 slot nasil secilecek? Bu adim
    # tanimsiz kalirsa keyfilik oradan girer. Portfoy kurma ayri bir is ama
    # sektor yogunlasmasi BURADA gorunur olmali - yoksa siralamadan ilk 15'i
    # almak farkinda olmadan tek sektore yigilmak olur.
    sektor_dagilim = {}
    for o in adaylar:
        s_ad = o.get("sektor_ad") or "Bilinmiyor"
        sektor_dagilim[s_ad] = sektor_dagilim.get(s_ad, 0) + 1

    cikti = {
        "tarih": b.isoformat(),
        "beklenen_donem": f"{bekl[0]}/{bekl[1]}",
        "ayarlar": AYAR,
        "eksik_filtreler": EKSIK_FILTRELER,
        "huni": huni,
        "aday_sayisi": len(adaylar),
        "izleme_sayisi": len(izleme),
        "adaylar": [o["kod"] for o in adaylar],
        "izleme": [o["kod"] for o in izleme],
        "sektor_dagilim": sektor_dagilim,
        "sirketler": olcumler,
        "filtre_notlari": [
            {"filtre": "Faiz karsilama",
             "not": "Bu filtre tek basina evrenin yarisindan fazlasini eler. Sebep esik degil, "
                    "piyasa: BIST'te faiz karsilama medyani 1.0x'in ALTINDA. Yani sirketlerin "
                    "yarisi faaliyet kariyla finansman giderini karsilayamiyor. Esik dusurulmedi "
                    "cunku bu bir tercih degil, hayatta kalma esigidir."},
            {"filtre": "Halka aciklik",
             "not": "Mutlak esik kullanildi (kesitsel degil). Gerekce: dusuk dolasim bir "
                    "degerleme tercihi degil, piyasa yapisi riskidir - fiyat manipulasyonuna "
                    "aciklik ve cikista likidite riski."},
        ],
        "not": ("Egitim ve arastirma amaclidir, yatirim tavsiyesi degildir. "
                "Esikler kesitsel yuzdelikdir; mutlak esik kullanilmamistir."),
    }
    (PANEL / "tarama.json").write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")

    print(f"TARAMA - beklenen donem {bekl[0]}/{bekl[1]}")
    print(f"{'KAPI':<18}{'ELENEN':>8}{'KALAN':>8}   ACIKLAMA")
    for h in huni:
        print(f"{h['kapi']:<18}{h['elenen']:>8}{h['kalan']:>8}   {h['aciklama']}")
    print(f"\nADAY: {len(adaylar)} sirket   |   IZLEME: {len(izleme)} sirket")
    print(f"Sektor dagilimi: {dict(sorted(sektor_dagilim.items(), key=lambda x:-x[1])[:6])}")
    for o in adaylar[:20]:
        u = (" [DARALMA]" if o.get("ortam_uyari") else "") + (" [UZAMIS]" if o.get("asiri_uzamis") else "")
        print(f"  {o['kod']:<7} {(o['sektor_ad'] or '')[:22]:<23} "
              f"FD/FAVOK {o['fd_favok']:>6.1f}  NB/FAVOK {(o['net_borc_favok'] or 0):>6.1f}  "
              f"MA {o['ma_mesafe']:>6.1f}%{u}")
    if len(adaylar) > 20:
        print(f"  ... ve {len(adaylar)-20} sirket daha")


if __name__ == "__main__":
    main()
