# -*- coding: utf-8 -*-
"""
GNC Insight - GECMISE DONUK PORTFOY TESTI (8 strateji, 5 yil)

AMAC: "Bu kurallarla 5 yil once baslasaydik ne olurdu?" sorusunu, gelecegi
BILMEDEN cevaplamak.

=============================================================================
DURUSTLUK BOLUMU - once bunu oku, sonuclara sonra bak
=============================================================================

Bu testte GIDERILEN look-ahead (gelecegi bilme) hatalari:

  1. BILANCO GECIKMESI. Bir ceyregin rakamlari, ceyrek bitiminden 75 gun
     sonrasina kadar KULLANILMAZ. Ornegin 2023/3 bilancosu 15 Haziran 2023'e
     kadar yok sayilir. Boylece "aciklanmadan once bilmek" imkansiz hale gelir.

  2. FIYAT. Karar gunu kapanisiyla karar verilir, ERTESI GUN acilisla degil
     ayni gun kapanisiyla islem yapildigi varsayilir - ama islem maliyeti
     bunu fazlasiyla karsilayacak sekilde yuksek tutulmustur.

  3. PIYASA DEGERI. Gecmis piyasa degeri, o gunun DUZELTILMIS fiyati x bugunku
     hisse sayisi ile hesaplanir. (Duzeltilmis seride bu ozdeslik gecerlidir;
     bugunku hisse sayisiyla bugunku fiyat, paneldeki PD'yi %0.0 sapmayla
     veriyor - dogrulandi.)

  4. ISLEM MALIYETI. Her alim ve her satimda %0.2 dusulur (komisyon + BSMV +
     spread payi). Eski portfoyde zararin %81'i alim-satimdan gelmisti;
     maliyetsiz test yanilticidir.

Bu testte GIDERILEMEYEN, sonuclari IYIMSER yapan hatalar:

  A. HAYATTA KALMA YANLILIGI. Evren, BUGUN borsada olan 472 sirkettir.
     2021-2025 arasinda borsadan cikan, birlesen veya batan sirketler veride
     YOK. Bu tek basina sonuclari yukari cekmeye yeter. Duzeltmek icin
     gecmis endeks bilesen listeleri gerekir - elimizde yok.

  B. YENIDEN IFADE (RESTATEMENT). TMS 29 enflasyon muhasebesi 2023 sonunda
     GECMIS donemleri de yeniden ifade etti. Elimizdeki 2021-2022 bilanco
     rakamlari, o tarihte yatirimcinin gordugu rakamlar DEGIL, bugun yeniden
     ifade edilmis halleridir. Yani bilanco temelli stratejilerde 2024 oncesi
     donem icin kismi bir bilgi sizmasi VARDIR. Ortadan kaldirilamaz;
     bu yuzden sonuclar 2024 oncesi ve sonrasi AYRI raporlanir.

  C. HALKA ARZ TARIHI. Bir sirketin fiyat serisi ne zaman basliyorsa o tarihte
     evrene girer - bu dogru. Ama halka arz oncesi donemde "yoktu" bilgisi
     disinda bir sey bilmiyoruz.

  D. ENDEKS UYELIGI. "O tarihte BIST 100'de miydi" bilgisi yok. Evren, likidite
     esigiyle yaklasik olarak sinirlandirilmistir.

SONUC: Bu test bir GETIRI VAADI DEGILDIR. Isi, bariz kotu kurallari elemek ve
stratejiler arasi GORELI farki gostermektir. Mutlak getiri rakamlarina degil,
stratejiler arasi siralamaya ve dususlere (drawdown) bakin.
=============================================================================

CIKTI: gnc-panel/gecmis_test.json
"""

import bisect
import json
import statistics
from datetime import date, timedelta
from pathlib import Path

import kalem_haritasi as KH

KLASOR = Path(__file__).parent
PANEL = KLASOR / "gnc-panel"

# ----------------------------------------------------------------- ayarlar
BASLANGIC = date(2021, 8, 31)
BITIS = date(2026, 7, 31)          # HATA DUZELTMESI (29 Agu): fiyat serileri AYNI
                                   # gunde bitmiyor (172 hisse 19 Agu, 119 hisse
                                   # 18 Agu, geri kalani daha erken - artimli
                                   # cekimin dogal sonucu). Son ay karar gununde
                                   # sadece o gunu iceren hisseler evrene giriyor,
                                   # evren 398'den 152'ye dusuyordu. Bu bir VERI
                                   # TAZELIK artifakti, gercek bir daralma degil.
                                   # Cozum: testi son TAM ayda bitir.
FIYAT_BAYATLIK_GUN = 7             # fiyat tam o gun yoksa en fazla bu kadar eski
                                   # bir kapanis kabul edilir (tatil/durdurma icin)
MIN_PD = 1_000_000_000             # LIKIDITE VEKILI: karar anindaki piyasa degeri
                                   # alt siniri. Gecmis HACIM verisi elimizde YOK;
                                   # piyasa degeri en iyi vekil. Bu filtre olmadan
                                   # momentum stratejisi sistematik olarak kucuk,
                                   # ince islem goren, manipulasyona acik hisseleri
                                   # seciyor ve gercekte alinamayacak bir getiri
                                   # uretiyor. Etkisi raporda AYRICA gosterilir.
BILANCO_GECIKME_GUN = 75           # ceyrek bitiminden sonra kullanilabilir hale gelme
ISLEM_MALIYETI = 0.002             # tek yon (%0.2)
POZISYON = 10                      # her portfoyde slot sayisi
MIN_FIYAT_GUN = 260                # evrene girmek icin gereken en az islem gunu (~1 yil)
BASLANGIC_SERMAYE = 100_000.0

CEYREK_SON = {3: (3, 31), 6: (6, 30), 9: (9, 30), 12: (12, 31)}


def donem_bitis(p):
    y, q = p.split("/")
    ay, gun = CEYREK_SON[int(q)]
    return date(int(y), ay, gun)


def dk(p):
    a, b = p.split("/")
    return (int(a), int(b))


# ----------------------------------------------------------------- veri

def veri_yukle():
    print("Veri yukleniyor...")
    piyasa = json.loads((PANEL / "sektor_hisse_veri.json").read_text(encoding="utf-8"))["hisseler"]
    liste = json.loads((PANEL / "sirket_listesi.json").read_text(encoding="utf-8"))["sirketler"]
    sektor = {s["kod"]: s.get("sektor") for s in liste}
    sektor_ad = {s["kod"]: s.get("sektor_ad") for s in liste}
    isim = {s["kod"]: s.get("ad") for s in liste}

    fiyat = {}
    for f in (PANEL / "hisse_gecmis").glob("*.json"):
        s = json.loads(f.read_text(encoding="utf-8")).get("seri", [])
        if s:
            fiyat[f.stem] = {r["tarih"]: r["kapanis"] for r in s if r.get("kapanis")}

    # HAYATTA KALMA YANLILIGI: borsadan cikmis sirketler de evrene girer.
    # Serileri cikis gununde biter, bu yuzden o gunden sonra evrene
    # otomatik olarak GIRMEZLER - fiili cikis tarihi budur.
    cikan_klasor = PANEL / "hisse_gecmis_cikan"
    cikan_sayi = 0
    if cikan_klasor.exists():
        for f in cikan_klasor.glob("*.json"):
            s = json.loads(f.read_text(encoding="utf-8")).get("seri", [])
            if s and f.stem not in fiyat:
                fiyat[f.stem] = {r["tarih"]: r["kapanis"] for r in s if r.get("kapanis")}
                cikan_sayi += 1
        print(f"  borsadan cikmis sirket eklendi: {cikan_sayi}")
    else:
        print("  UYARI: hisse_gecmis_cikan/ YOK -> hayatta kalma yanliligi DEVAM EDIYOR. "
              "'python kap_evren_cek.py --doldur' calistirin.")

    finansal = {}
    for f in (PANEL / "finansal").glob("*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        fmt = KH.format_belirle(d)
        if fmt != "SANAYI":       # banka/sigorta ayri oran seti ister - testte yok
            continue
        ix, ixc = KH._indeks(d), KH._indeks_coklu(d)
        donemler = sorted(d.get("donemler", []), key=dk)
        finansal[f.stem] = {"veri": d, "fmt": fmt, "ix": ix, "ixc": ixc,
                            "donemler": donemler,
                            "bitis": {p: donem_bitis(p) for p in donemler}}

    try:
        karantina = json.loads((PANEL / "karantina.json").read_text(encoding="utf-8"))["sirketler"]
    except FileNotFoundError:
        karantina = {}

    # VBTS tedbir araliklari. Dosya yoksa filtre SESSIZCE devre disi kalmaz -
    # ekrana yazilir, cunku eksik filtre gizlenmemelidir.
    tedbir = {}
    tp = PANEL / "tedbir.json"
    if tp.exists():
        tedbir = json.loads(tp.read_text(encoding="utf-8")).get("kod_araliklari", {})
        print(f"  VBTS tedbir: {len(tedbir)} kod icin arilik yuklendi")
    else:
        print("  UYARI: tedbir.json YOK -> tedbirli hisseler evrende kalacak. "
              "Once 'python kap_tedbir_cek.py' calistirin.")

    print(f"  fiyat serisi: {len(fiyat)} | finansal (SANAYI): {len(finansal)}")
    return fiyat, finansal, piyasa, sektor, sektor_ad, isim, karantina, tedbir


def fiyat_al(seri, tarihler, gun, max_bayat=None):
    """gun tarihindeki kapanis; o gun yoksa en fazla max_bayat gun oncesi."""
    i = bisect.bisect_right(tarihler, gun) - 1
    if i < 0:
        return None
    t = tarihler[i]
    if max_bayat is not None:
        fark = (date.fromisoformat(gun) - date.fromisoformat(t)).days
        if fark > max_bayat:
            return None
    return seri[t]


def islem_gunleri(fiyat):
    g = set()
    for s in fiyat.values():
        g |= s.keys()
    return sorted(g)


def ay_sonlari(gunler):
    """Her ayin son islem gunu - karar gunleri."""
    son = {}
    for g in gunler:
        son[g[:7]] = g
    return [v for k, v in sorted(son.items())]


# ----------------------------------------------------------------- olcum

def ttm_asof(F, alan, p_index):
    """p_index: donemler listesindeki indeks. TTM = bu + gecen_yil_12 - gecen_yil_ayni."""
    don = F["donemler"]
    p = don[p_index]
    y, q = dk(p)
    d = lambda pp: KH.deger(F["veri"], alan, pp, F["fmt"], F["ix"], F["ixc"])
    if q == 12:
        return d(p)
    a, b, c = d(p), d(f"{y-1}/12"), d(f"{y-1}/{q}")
    if None in (a, b, c):
        return None
    return a + b - c


def olcum_asof(kod, F, gun, fiyat_g, hisse_sayisi):
    """
    gun tarihinde BILINEBILECEK olculer. Yayin gecikmesi uygulanir.
    Doner: dict veya None (yeterli veri yoksa).
    """
    g = date.fromisoformat(gun)
    kullanilabilir = [i for i, p in enumerate(F["donemler"])
                      if F["bitis"][p] + timedelta(days=BILANCO_GECIKME_GUN) <= g]
    if not kullanilabilir:
        return None
    i = kullanilabilir[-1]
    p = F["donemler"][i]
    D = lambda a: KH.deger(F["veri"], a, p, F["fmt"], F["ix"], F["ixc"])
    T = lambda a: ttm_asof(F, a, i)

    if not fiyat_g or not hisse_sayisi:
        return None

    pd_ = fiyat_g * hisse_sayisi
    ozk, tv = D("ozkaynak"), D("toplam_varlik")
    nakit, borc = D("nakit"), D("finansal_borc")
    fk, am = T("fin_oncesi_fk"), T("amortisman")
    isn, nk = T("isletme_nakit"), T("net_kar")
    gelir, fg = T("gelir"), T("finansman_gideri")

    favok = (fk + am) if None not in (fk, am) else None
    nb = (borc - nakit) if None not in (borc, nakit) else None
    return {
        "donem": p, "pd": pd_, "fiyat": fiyat_g,
        "ozkaynak": ozk, "toplam_varlik": tv, "net_borc": nb, "favok": favok,
        "isletme_nakit": isn, "net_kar": nk, "gelir": gelir,
        "fd_favok": ((pd_ + nb) / favok) if (nb is not None and favok and favok > 0) else None,
        "net_borc_favok": (nb / favok) if (nb is not None and favok and favok > 0) else None,
        "tahakkuk": ((nk - isn) / tv) if None not in (nk, isn, tv) and tv else None,
        "faiz_karsilama": (fk / abs(fg)) if (fk is not None and fg) else None,
        "pd_dd": (pd_ / ozk) if (ozk and ozk > 0) else None,
        "donem_index": i,
    }


def getiri(seri, gun, geri_gun):
    """gun'den geri_gun once ile arasindaki yuzde getiri."""
    g = date.fromisoformat(gun)
    hedef = (g - timedelta(days=geri_gun)).isoformat()
    tarihler = [t for t in seri if t <= hedef]
    if not tarihler or gun not in seri:
        return None
    eski = seri[max(tarihler)]
    return (seri[gun] / eski - 1) * 100 if eski else None


def ort_mesafe(seri, gun, n=200):
    tarihler = sorted(t for t in seri if t <= gun)
    if len(tarihler) < n:
        return None
    son = seri[tarihler[-1]]
    ort = statistics.fmean(seri[t] for t in tarihler[-n:])
    return (son / ort - 1) * 100 if ort else None


# ----------------------------------------------------------------- stratejiler
#
# Her strateji TEK bir boyutta digerlerinden ayrilir. Boylece bir strateji one
# ciktiginda farkin NEREDEN geldigi bilinir. Hepsinde ortak olan: aylik karar,
# esit agirlik, ayni evren, ayni islem maliyeti.

def _ilk_n(adaylar, anahtar, ters=False, n=POZISYON):
    tmp = [(k, v) for k, v in adaylar if v is not None]
    tmp.sort(key=lambda x: x[1], reverse=ters)
    return [k for k, _ in tmp[:n]]


def st_piyasa(ev):
    """1) KONTROL GRUBU. Hicbir secim yok - uygun evrenin tamami esit agirlik.
    Digerlerinin karsilastirilacagi taban. Bunu gecemeyen strateji ise yaramaz."""
    return list(ev.keys())


def st_saglam(ev):
    """2) SADECE DAYANIKLILIK. Degerleme ve fiyat bakilmaz."""
    uygun = [(k, o) for k, o in ev.items()
             if o["isletme_nakit"] and o["isletme_nakit"] > 0
             and o["favok"] and o["favok"] > 0
             and o["faiz_karsilama"] is not None and o["faiz_karsilama"] >= 1.0]
    return _ilk_n([(k, o["net_borc_favok"]) for k, o in uygun], None)


def st_ucuz(ev):
    """3) SADECE DEGERLEME. Kalite filtresi YOK - ucuzluk tek basina calisiyor mu?"""
    return _ilk_n([(k, o["fd_favok"]) for k, o in ev.items()
                   if o["fd_favok"] is not None and o["fd_favok"] > 0], None)


def st_nakit_kalite(ev):
    """4) SADECE TAHAKKUK KALITESI. BIST'te akademik kaniti en tutarli olcu.
    Dusuk tahakkuk = kar nakde donuyor = iyi."""
    return _ilk_n([(k, o["tahakkuk"]) for k, o in ev.items()], None)


def st_trend(ev):
    """5) SADECE FIYAT MOMENTUMU. 200g ortalama ustunde olanlar arasindan
    son 6 ayin en guclusu."""
    uygun = [(k, o["mom6"]) for k, o in ev.items()
             if o.get("ma200") is not None and o["ma200"] > 0 and o.get("mom6") is not None]
    return _ilk_n(uygun, None, ters=True)


def st_ters(ev):
    """6) TERS (CONTRARIAN). Son 12 ayda en cok DUSENLER.
    Momentumun tam tersi - akademideki celiskiyi dogrudan sinar."""
    return _ilk_n([(k, o.get("mom12")) for k, o in ev.items()], None)


def st_buyume(ev):
    """7) SADECE BUYUME. Gelirin yillik buyumesi en yuksek olanlar."""
    return _ilk_n([(k, o.get("gelir_buyume")) for k, o in ev.items()], None, ters=True)


def st_sistem(ev):
    """8) TAM KURAL SETI (panelin tarama motoru).
    Eleme -> degerleme siralamasi -> fiyat vetosu."""
    uygun = {}
    for k, o in ev.items():
        if not (o["isletme_nakit"] and o["isletme_nakit"] > 0):
            continue
        if not (o["favok"] and o["favok"] > 0):
            continue
        if o["faiz_karsilama"] is None or o["faiz_karsilama"] < 1.0:
            continue
        if o["tahakkuk"] is None or o["fd_favok"] is None:
            continue
        if o.get("ma200") is None or o["ma200"] < 0:      # fiyat vetosu
            continue
        uygun[k] = o
    if not uygun:
        return []
    # kesitsel elemeler: en kotu %25 tahakkuk, en borclu %25
    tah = sorted(o["tahakkuk"] for o in uygun.values())
    brc = sorted(o["net_borc_favok"] for o in uygun.values()
                 if o["net_borc_favok"] is not None and o["net_borc_favok"] > 0)
    tah_esik = tah[int(len(tah) * 0.75)] if len(tah) >= 8 else None
    brc_esik = brc[int(len(brc) * 0.75)] if len(brc) >= 8 else None
    kalan = []
    for k, o in uygun.items():
        if tah_esik is not None and o["tahakkuk"] > tah_esik:
            continue
        if brc_esik is not None and o["net_borc_favok"] is not None and o["net_borc_favok"] > brc_esik:
            continue
        kalan.append((k, o["fd_favok"]))
    return _ilk_n(kalan, None)


STRATEJILER = [
    ("piyasa",       "Piyasa (Kontrol)",  "Seçim yok — uygun evrenin tamamı, eşit ağırlık", st_piyasa),
    ("saglam",       "Sağlam",            "Sadece dayanıklılık: nakit akışı, faiz karşılama, düşük borç", st_saglam),
    ("ucuz",         "Ucuz",              "Sadece değerleme: en düşük FD/FAVÖK", st_ucuz),
    ("nakit_kalite", "Nakit Kalite",      "Sadece tahakkuk kalitesi: kârı nakde dönen şirketler", st_nakit_kalite),
    ("trend",        "Trend",             "Sadece fiyat: 200 gün ortalaması üstü + 6 ay momentum", st_trend),
    ("ters",         "Ters",              "Son 12 ayda en çok düşenler (contrarian)", st_ters),
    ("buyume",       "Büyüme",            "Sadece gelir büyümesi", st_buyume),
    ("sistem",       "Sistem (Tarama)",   "Panelin tam kural seti: eleme + değerleme + fiyat vetosu", st_sistem),
]


# ----------------------------------------------------------------- simulasyon

def evren_kur(gun, fiyat, tarih_ix, finansal, hisse_sayisi, karantina, min_pd=MIN_PD,
              dislanan=None, tedbir=None):
    """gun tarihinde BILINEBILECEK olculerle uygun evren."""
    ev = {}
    yil = int(gun[:4])
    for kod, F in finansal.items():
        if dislanan and kod in dislanan:
            continue
        seri = fiyat.get(kod)
        if not seri:
            continue
        tarihler = tarih_ix[kod]
        f_gun = fiyat_al(seri, tarihler, gun, FIYAT_BAYATLIK_GUN)
        if f_gun is None:
            continue
        if bisect.bisect_right(tarihler, gun) < MIN_FIYAT_GUN:
            continue
        # karantina: o yil veya onceki yil supheliyse evrene alma
        kar = karantina.get(kod, [])
        if any(y in (yil, yil - 1) for y in kar):
            continue
        # VBTS: o gun tedbirliyse ALINAMAZ. Tek fiyat isleme alinmis ya da
        # emir paketi tedbirli bir hisse normal alinip satilamaz; testin
        # bunu gormezden gelmesi gercek disi bir avantaj yaratir.
        if tedbir and any(a["baslangic"] <= gun <= a["bitis"]
                          for a in tedbir.get(kod, ())):
            continue
        o = olcum_asof(kod, F, gun, f_gun, hisse_sayisi.get(kod))
        if not o:
            continue
        if min_pd and o["pd"] < min_pd:      # likidite vekili
            continue
        o["ma200"] = ort_mesafe(seri, gun, 200)
        o["mom6"] = getiri(seri, gun, 182)
        o["mom12"] = getiri(seri, gun, 365)
        # gelir buyumesi: TTM gelir / bir yil onceki ayni donemin TTM geliri
        i = o["donem_index"]
        gecen = None
        if i >= 4:
            gecen = ttm_asof(F, "gelir", i - 4)
        o["gelir_buyume"] = ((o["gelir"] / gecen - 1) * 100
                             if (o["gelir"] and gecen and gecen > 0) else None)
        ev[kod] = o
    return ev


def portfoy_degeri(pozisyonlar, gun, fiyat, son_bilinen):
    """Pozisyonlar: {kod: lot}. Fiyati olmayan gunlerde son bilinen fiyat kullanilir."""
    t = 0.0
    for kod, lot in pozisyonlar.items():
        f = fiyat.get(kod, {}).get(gun) or son_bilinen.get(kod)
        if f is None:
            continue
        t += lot * f
    return t


def calistir(veri, min_pd=MIN_PD, dislanan=None):
    fiyat, finansal, piyasa, sektor, sektor_ad, isim, karantina, tedbir = veri
    tarih_ix = {k: sorted(v) for k, v in fiyat.items()}

    # hisse sayisi = bugunku odenmis sermaye (nominal 1 TL)
    hisse_sayisi = {}
    for kod, F in finansal.items():
        if F["donemler"]:
            v = KH.deger(F["veri"], "odenmis_sermaye", F["donemler"][-1], F["fmt"], F["ix"], F["ixc"])
            if v:
                hisse_sayisi[kod] = v

    gunler = [g for g in islem_gunleri(fiyat)
              if BASLANGIC.isoformat() <= g <= BITIS.isoformat()]
    kararlar = ay_sonlari(gunler)
    print(f"  karar gunu: {len(kararlar)} ay ({kararlar[0]} - {kararlar[-1]})")

    durum = {kid: {"nakit": BASLANGIC_SERMAYE, "poz": {}, "seri": [], "islemler": [],
                   "islem_sayisi": 0, "maliyet": 0.0}
             for kid, _, _, _ in STRATEJILER}
    son_bilinen = {}
    evren_boyu = []
    bekleyen = None

    for gi, gun in enumerate(gunler):
        for kod, s in fiyat.items():
            if gun in s:
                son_bilinen[kod] = s[gun]

        # ---------------- T+1 UYGULAMA -----------------------------------
        # ONCEKI surumde karar gunu kapanisiyla karar verilip AYNI kapanistan
        # islem yapiliyordu. Gercekte kapanisi gorup ertesi gun alirsin; bu
        # bir gunluk bilgi avantajidir ve ozellikle momentum stratejisini
        # sisirir. Artik secim karar gunu yapilir, ISLEM ERTESI ISLEM GUNUNUN
        # kapanisindan gerceklesir.
        if bekleyen and bekleyen["gun"] != gun:
            for kid, secim in bekleyen["emirler"].items():
                d = durum[kid]
                gecerli = [k for k in secim if fiyat.get(k, {}).get(gun) or son_bilinen.get(k)]
                if not gecerli:
                    continue
                deger = d["nakit"] + portfoy_degeri(d["poz"], gun, fiyat, son_bilinen)
                maliyet = 0.0
                for kod, lot in d["poz"].items():
                    f = fiyat.get(kod, {}).get(gun) or son_bilinen.get(kod)
                    if kod not in gecerli and f:
                        maliyet += lot * f * ISLEM_MALIYETI
                        d["islem_sayisi"] += 1
                hedef = deger / len(gecerli)
                for kod in gecerli:
                    f = fiyat.get(kod, {}).get(gun) or son_bilinen.get(kod)
                    eski = d["poz"].get(kod, 0.0)
                    if eski == 0:
                        d["islem_sayisi"] += 1
                    maliyet += abs(hedef / f - eski) * f * ISLEM_MALIYETI
                deger -= maliyet
                d["maliyet"] += maliyet
                hedef = deger / len(gecerli)
                d["poz"] = {k: hedef / (fiyat.get(k, {}).get(gun) or son_bilinen[k])
                            for k in gecerli}
                d["nakit"] = 0.0
                d["islemler"].append({"tarih": gun, "adet": len(gecerli),
                                      "hisseler": sorted(gecerli)})
            bekleyen = None

        if gun in kararlar:
            ev = evren_kur(gun, fiyat, tarih_ix, finansal, hisse_sayisi, karantina, min_pd,
                           dislanan, tedbir)
            evren_boyu.append({"tarih": gun, "evren": len(ev)})
            bekleyen = {"gun": gun, "emirler": {}}
            for kid, ad, aciklama, fn in STRATEJILER:
                secim = [k for k in fn(ev) if ev[k]["fiyat"]]
                if secim:
                    bekleyen["emirler"][kid] = secim

        if gi % 5 == 0 or gun == gunler[-1]:
            for kid, *_ in STRATEJILER:
                d = durum[kid]
                v = d["nakit"] + portfoy_degeri(d["poz"], gun, fiyat, son_bilinen)
                d["seri"].append({"tarih": gun, "deger": round(v, 2)})

    return durum, evren_boyu, kararlar


def olcut(seri):
    if len(seri) < 2:
        return {}
    ilk, son = seri[0]["deger"], seri[-1]["deger"]
    toplam = (son / ilk - 1) * 100
    yil = (date.fromisoformat(seri[-1]["tarih"]) - date.fromisoformat(seri[0]["tarih"])).days / 365.25
    yillik = ((son / ilk) ** (1 / yil) - 1) * 100 if yil > 0 else 0
    zirve, maxdd, dd_tarih = seri[0]["deger"], 0.0, None
    for r in seri:
        zirve = max(zirve, r["deger"])
        dd = (r["deger"] / zirve - 1) * 100
        if dd < maxdd:
            maxdd, dd_tarih = dd, r["tarih"]
    # oynaklik (gunluk degil, 5 gunluk orneklem uzerinden yillik)
    getiriler = [seri[i]["deger"] / seri[i-1]["deger"] - 1
                 for i in range(1, len(seri)) if seri[i-1]["deger"]]
    oyn = (statistics.pstdev(getiriler) * (252 / 5) ** 0.5 * 100) if len(getiriler) > 2 else 0
    return {"toplam_getiri": round(toplam, 1), "yillik_getiri": round(yillik, 1),
            "max_dusus": round(maxdd, 1), "max_dusus_tarih": dd_tarih,
            "oynaklik": round(oyn, 1),
            "getiri_dusus_orani": round(abs(yillik / maxdd), 2) if maxdd else None}


YILLAR = [("2021-09", "2022-08"), ("2022-09", "2023-08"), ("2023-09", "2024-08"),
          ("2024-09", "2025-08"), ("2025-09", "2026-07")]
DONEMLER = [("Kirlenmiş", "2021-08-01", "2023-12-31",
             "TMS 29 geçmiş bilançoları yeniden ifade etti — bilgi sızması var"),
            ("Temiz", "2024-01-01", "2026-07-31",
             "Enflasyon muhasebesi sonrası, yeniden ifade riski yok")]


def dilim_getiri(seri, bas, bit):
    s = [r for r in seri if bas <= r["tarih"] <= bit]
    if len(s) < 3:
        return None
    ilk, son = s[0]["deger"], s[-1]["deger"]
    zirve, dd = ilk, 0.0
    for r in s:
        zirve = max(zirve, r["deger"])
        dd = min(dd, (r["deger"] / zirve - 1) * 100)
    return {"getiri": round((son / ilk - 1) * 100, 1), "max_dusus": round(dd, 1)}


def alt_donemler(seri):
    return {
        "yillik": [{"etiket": f"{a[:4]}/{b[2:4]}", **(dilim_getiri(seri, a + "-01", b + "-31") or {})}
                   for a, b in YILLAR],
        "donem": [{"ad": ad, "aciklama": ac, **(dilim_getiri(seri, b1, b2) or {})}
                  for ad, b1, b2, ac in DONEMLER],
    }


def rapor_yaz(durum, etiket):
    print(f"\n{'='*78}\n{etiket}\n{'='*78}")
    print(f"{'STRATEJI':<20}{'TOPLAM':>9}{'YILLIK':>9}{'MAX DUS':>9}{'OYNAK':>8}{'G/D':>6}{'ISLEM':>7}{'MALIYET':>10}")
    print("-" * 78)
    satirlar = []
    for kid, ad, aciklama, _ in STRATEJILER:
        d = durum[kid]
        o = olcut(d["seri"])
        satirlar.append((kid, ad, aciklama, o, d))
        print(f"{ad:<20}{o.get('toplam_getiri',0):>8.1f}%{o.get('yillik_getiri',0):>8.1f}%"
              f"{o.get('max_dusus',0):>8.1f}%{o.get('oynaklik',0):>7.1f}%"
              f"{str(o.get('getiri_dusus_orani','-')):>6}{d['islem_sayisi']:>7}"
              f"{d['maliyet']:>9,.0f}")
    return satirlar


def main():
    veri = veri_yukle()

    # ANA SENARYO: likidite vekili (piyasa degeri tabani) UYGULANIR
    durum, evren_boyu, kararlar = calistir(veri, min_pd=MIN_PD)
    ana = rapor_yaz(durum, f"ANA SENARYO - likidite tabani {MIN_PD/1e9:.1f} mr TL piyasa degeri")

    # KIRILGANLIK TESTI: ayni kurallar, likidite tabani YOK
    durum2, evren_boyu2, _ = calistir(veri, min_pd=0)
    yok = rapor_yaz(durum2, "KIRILGANLIK TESTI - likidite tabani YOK (gercekte alinamaz)")

    fiyat = veri[0]
    xu = {}
    xp = PANEL / "endeks_gecmis" / "XU100.json"
    if xp.exists():
        for r in json.loads(xp.read_text(encoding="utf-8")).get("seri", []):
            if r.get("kapanis"):
                xu[r["tarih"]] = r["kapanis"]
    xu_seri, ilk = [], None
    for r in durum["piyasa"]["seri"]:
        v = xu.get(r["tarih"])
        if v is None:
            continue
        if ilk is None:
            ilk = v
        xu_seri.append({"tarih": r["tarih"], "deger": round(BASLANGIC_SERMAYE * v / ilk, 2)})
    if xu_seri:
        o = olcut(xu_seri)
        print("-" * 78)
        print(f"{'BIST 100':<20}{o['toplam_getiri']:>8.1f}%{o['yillik_getiri']:>8.1f}%"
              f"{o['max_dusus']:>8.1f}%{o['oynaklik']:>7.1f}%{str(o.get('getiri_dusus_orani','-')):>6}")

    print(f"\n{'STRATEJI':<20}{'LIKIDITE FILTRELI':>19}{'FILTRESIZ':>12}{'FARK':>10}")
    print("-" * 62)
    for (kid, ad, _, o1, _), (_, _, _, o2, _) in zip(ana, yok):
        f1, f2 = o1.get("yillik_getiri", 0), o2.get("yillik_getiri", 0)
        print(f"{ad:<20}{f1:>18.1f}%{f2:>11.1f}%{f2-f1:>+9.1f}p")

    sonuc = {
        "tarih": date.today().isoformat(),
        "baslangic": BASLANGIC.isoformat(), "bitis": BITIS.isoformat(),
        "baslangic_sermaye": BASLANGIC_SERMAYE, "pozisyon": POZISYON,
        "islem_maliyeti_tek_yon": ISLEM_MALIYETI,
        "bilanco_gecikme_gun": BILANCO_GECIKME_GUN,
        "min_piyasa_degeri": MIN_PD,
        "karar_sayisi": len(kararlar),
        "evren_boyu": evren_boyu,
        "benchmark": {"ad": "BIST 100", "seri": xu_seri, "olcut": olcut(xu_seri),
                      "alt_donemler": alt_donemler(xu_seri)},
        "stratejiler": [{
            "id": kid, "ad": ad, "aciklama": aciklama,
            "seri": d["seri"], "olcut": o,
            "olcut_filtresiz": olcut(durum2[kid]["seri"]),
            "alt_donemler": alt_donemler(d["seri"]),
            "islem_sayisi": d["islem_sayisi"],
            "toplam_maliyet": round(d["maliyet"], 0),
            "son_portfoy": d["islemler"][-1]["hisseler"] if d["islemler"] else [],
            "islem_gecmisi": d["islemler"],
        } for kid, ad, aciklama, o, d in ana],
        "uyarilar": [
            "Hayatta kalma yanlılığı: evren bugün borsada olan şirketlerden oluşur; "
            "2021-2025 arası çıkan veya batan şirketler veride yok. Sonuçları YUKARI çeker.",
            "Yeniden ifade: TMS 29, 2023 sonunda geçmiş bilançoları da yeniden ifade etti. "
            "2024 öncesi bilanço temelli sonuçlarda kısmi bilgi sızması vardır.",
            "Likidite: geçmiş işlem hacmi verisi yok. Piyasa değeri tabanı vekil olarak "
            "kullanıldı. Filtresiz koşu, bu vekilin ne kadar belirleyici olduğunu gösterir.",
            "Endeks üyeliği: 'o tarihte BIST 100'de miydi' bilgisi yok.",
            "Bu bir getiri vaadi değildir. Mutlak rakamlara değil, stratejiler arası "
            "göreli farka ve düşüşlere bakılmalıdır.",
            "Dönem farkı yanıltıcı olabilir: 2024 sonrası getiriler TÜM stratejilerde "
            "ve BIST 100'de birden düştü. Bu sadece veri kirlenmesi değil, enflasyonun "
            "gerilemesiyle nominal getirilerin daralmasıdır. İki etki iç içe.",
        ],
    }
    (PANEL / "gecmis_test.json").write_text(json.dumps(sonuc, ensure_ascii=False), encoding="utf-8")
    print(f"\n-> gnc-panel/gecmis_test.json")
    print(f"   evren: {evren_boyu[0]['evren']} ({evren_boyu[0]['tarih']}) -> "
          f"{evren_boyu[-1]['evren']} ({evren_boyu[-1]['tarih']})")


if __name__ == "__main__":
    main()
