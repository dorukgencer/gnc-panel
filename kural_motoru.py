# -*- coding: utf-8 -*-
"""
GNC Insight - KURAL MOTORU (kural laboratuvarı)

AMAÇ: "4 kuralla test edeyim, sonra 3'e düşüreyim, sonra 6 yapayım" diyebilmek.
Her kural BAĞIMSIZ bir birimdir; istenen kombinasyon serbestçe kurulup
geçmişe dönük test edilir ve hepsi aynı ölçütlerle karşılaştırılır.

MİMARİ KARARI — NEDEN HIZLI:
  Saf yaklaşım her kombinasyon için testi baştan çalıştırmaktır: 60 karar günü ×
  450 şirket × ölçüm hesabı ≈ 15 saniye. 200 kombinasyon = 50 dakika. Kullanılamaz.
  Bunun yerine ölçümler BİR KEZ hesaplanıp bir panele (tarih × şirket × ölçü)
  yazılır. Sonrasında her kural kombinasyonu bu panel üzerinde saf süzme ve
  sıralamadır — milisaniyeler sürer. Yüzlerce kombinasyon saniyeler içinde
  test edilebilir.

ÜÇ KURAL TÜRÜ:
  SÜZGEÇ (filtre) : şirketi eler / bırakır. İstenen kadarı seçilebilir.
  SIRALAMA        : kalanları sıralar. TAM OLARAK BİRİ seçilir.
  KORUMA (guard)  : portföy seviyesinde nakde geçme koşulu. En fazla biri.

DÜRÜSTLÜK: Bu motor, gecmis_test.py'deki look-ahead korumalarının AYNISINI
kullanır — bilanço yayın gecikmesi, T+1 uygulama, işlem maliyeti, tedbir,
borsadan çıkanlar. Kombinasyon aramak, gerçekçilikten ödün vermez.

AŞIRI UYDURMA (overfitting) UYARISI: Yüzlerce kombinasyon deneyip en iyisini
seçmek, veriye uydurmanın ta kendisidir. Bu yüzden motor her kombinasyon için
sadece getiriyi değil, DÖNEM İSTİKRARINI ve REJİM DAYANIKLILIĞINI de raporlar;
ve "en iyi" seçilirken bunlar gösterilir. Tek bir dönemde parlayan kombinasyon
işaretlenir.
"""

import json
import statistics
from datetime import date, timedelta
from pathlib import Path

import gecmis_test as GT
import kalem_haritasi as KH

KLASOR = Path(__file__).parent
PANEL = KLASOR / "gnc-panel"


# ===================================================================== ENFLASYON
# NEDEN: %30 enflasyonda "gelir buyumesi > 0" bir suzgec degildir - evrenin
# ucte ikisi gecer (olculdu: 262/387). Gercekte kuculen sirket "buyuyor"
# sayilir. Temel katmandaki buyume kurallari bu yuzden REEL calisir:
# esik sifir degil, o ayda BILINEN yillik TUFE'dir.
#
# "Bilinen": TUIK enflasyonu ayin basinda bir onceki ay icin acikladigi icin
# karar gununden onceki son yayinlanmis deger kullanilir. Ileri bakis yok.

_TUFE_ONBELLEK = {}


def tufe_asof(gun):
    """gun tarihinde BILINEN son yillik TUFE (%). Yoksa None."""
    if not _TUFE_ONBELLEK:
        for ay, v in rejim_serisi().items():
            t = v.get("tufe_yillik")
            if t is not None:
                _TUFE_ONBELLEK[ay] = t
    if not _TUFE_ONBELLEK:
        return None
    ay = gun[:7]
    uygun = [a for a in _TUFE_ONBELLEK if a < ay]      # kesin gecmis
    return _TUFE_ONBELLEK[max(uygun)] if uygun else None


# ===================================================================== SÜZGEÇLER
# Her süzgeç: (olcum, baglam) -> True (KALSIN) / False (ELENSIN)
# baglam: o karar gününün kesitsel eşikleri

def _f_nakit_akisi(o, b):
    return o.get("isletme_nakit") is not None and o["isletme_nakit"] > 0

def _f_favok_pozitif(o, b):
    return o.get("favok") is not None and o["favok"] > 0

def _f_faiz_karsilama(o, b):
    return o.get("faiz_karsilama") is not None and o["faiz_karsilama"] >= 1.0

def _f_borcluluk(o, b):
    e = b.get("borc_esik")
    v = o.get("net_borc_favok")
    return e is None or v is None or v <= e

def _f_tahakkuk(o, b):
    e = b.get("tahakkuk_esik")
    v = o.get("tahakkuk")
    if v is None:
        return False
    return e is None or v <= e

def _f_ucuzluk(o, b):
    e = b.get("deger_esik")
    v = o.get("fd_favok")
    if v is None or v <= 0:
        return False
    return e is None or v <= e

def _f_ma_ustu(o, b):
    return o.get("ma200") is not None and o["ma200"] > 0

def _f_momentum_pozitif(o, b):
    return o.get("mom6") is not None and o["mom6"] > 0

def _f_asiri_uzamamis(o, b):
    return o.get("ma200") is None or o["ma200"] <= 40

def _f_buyume_pozitif(o, b):
    return o.get("gelir_buyume") is not None and o["gelir_buyume"] > 0

def _f_kar_pozitif(o, b):
    return o.get("net_kar") is not None and o["net_kar"] > 0

def _f_ozkaynak_saglam(o, b):
    return o.get("pd_dd") is not None and 0 < o["pd_dd"] <= (b.get("pddd_esik") or 1e9)


# --- TEMEL KATMAN -----------------------------------------------------------
# TMS 29 notu: buradaki olculerin hepsi ORAN ya da AYNI BAZDA buyumedir; pay
# ve payda ayni donemin ayni bazinda oldugu icin yeniden ifadeden etkilenmez.
# ROE/ROA/ROIC/F/K bilerek SUZGEC olarak eklenmedi - 2024 oncesinde mekanik
# olarak kayarlar; sadece bilgi olarak tasiniyorlar.

def _f_reel_buyume(o, b):
    """Gelir buyumesi ENFLASYONUN uzerinde mi - yani gercekten buyuyor mu."""
    t = b.get("tufe")
    if t is None or o.get("gelir_buyume") is None:
        return False
    return o["gelir_buyume"] > t

def _f_ozkaynak_reel(o, b):
    t = b.get("tufe")
    if t is None or o.get("ozkaynak_buyume") is None:
        return False
    return o["ozkaynak_buyume"] > t

def _f_marj_genisleyen(o, b):
    return o.get("marj_trend") is not None and o["marj_trend"] > 0

def _f_marj_ust_yari(o, b):
    e = b.get("marj_medyan")
    return e is not None and o.get("favok_marj") is not None and o["favok_marj"] > e

def _f_nakit_donusum(o, b):
    return o.get("nakit_donusum") is not None and o["nakit_donusum"] >= 0.8

def _f_kar_istikrarli(o, b):
    return o.get("kar_istikrar") is not None and o["kar_istikrar"] >= 75

def _f_yp_riski_dusuk(o, b):
    """Net YP pozisyonu ozkaynagin %25'inden fazla ACIK degil.

    BIST'e ozgu risk: kur soku, acik YP pozisyonu tasiyan sirketin ozkaynagini
    dogrudan yer. Veri yoksa ELEMEZ - eksik veri ceza sebebi degildir."""
    v = o.get("yp_ozkaynak")
    return True if v is None else v > -0.25

def _f_borc_ozkaynak(o, b):
    e = b.get("borc_ozk_esik")
    if e is None or o.get("borc_ozkaynak") is None:
        return True
    return o["borc_ozkaynak"] <= e


SUZGECLER = {
    "nakit_akisi":     ("İşletme nakit akışı pozitif", "Kârın nakde döndüğünün en basit kanıtı", _f_nakit_akisi),
    "favok_pozitif":   ("FAVÖK pozitif", "Faaliyetten para kazanıyor mu", _f_favok_pozitif),
    "faiz_karsilama":  ("Faiz karşılama ≥ 1", "Faaliyet kârı finansman giderini karşılıyor mu", _f_faiz_karsilama),
    "borcluluk":       ("Borçluluk en kötü %25 elenir", "Net Borç/FAVÖK kesitsel eşik", _f_borcluluk),
    "tahakkuk":        ("Tahakkuk kalitesi en kötü %25 elenir", "BIST'te kanıtı en tutarlı ölçü", _f_tahakkuk),
    "ucuzluk":         ("Değerlemede en pahalı %25 elenir", "Sektör içi FD/FAVÖK", _f_ucuzluk),
    "ma_ustu":         ("200 gün ortalamasının üstünde", "Zamanlama vetosu — seçim değil", _f_ma_ustu),
    "momentum_pozitif":("Son 6 ay getirisi pozitif", "Fiyat yönü teyidi", _f_momentum_pozitif),
    "asiri_uzamamis":  ("Ortalamanın %40'ından fazla üstünde değil", "Aşırı koşmuşa girme", _f_asiri_uzamamis),
    "buyume_pozitif":  ("Gelir büyümesi pozitif", "Küçülen şirketi alma", _f_buyume_pozitif),
    "kar_pozitif":     ("Net kâr pozitif", "Zarar eden şirketi alma", _f_kar_pozitif),
    "ozkaynak_saglam": ("PD/DD makul aralıkta", "Defter değerine göre aşırı pahalı değil", _f_ozkaynak_saglam),

    # --- temel katman ---
    "reel_buyume":     ("Gelir büyümesi enflasyonun üstünde", "REEL büyüme. 'Büyüme > 0' %30 enflasyonda evrenin %68'ini geçirir; bu %17'sini", _f_reel_buyume),
    "ozkaynak_reel":   ("Özkaynak büyümesi enflasyonun üstünde", "Sermaye reel olarak büyüyor mu", _f_ozkaynak_reel),
    "marj_genisleyen": ("FAVÖK marjı geçen yıla göre artmış", "Marj yönü, marj seviyesinden daha çok şey söyler", _f_marj_genisleyen),
    "marj_ust_yari":   ("FAVÖK marjı evren medyanının üstünde", "Kesitsel marj eşiği — mutlak eşik değil", _f_marj_ust_yari),
    "nakit_donusum":   ("İşletme nakdi / FAVÖK ≥ 0.8", "FAVÖK'ün nakde dönme oranı", _f_nakit_donusum),
    "kar_istikrarli":  ("Son 8 çeyreğin en az 6'sında kâr", "Kâr seviyesi değil, SÜREKLİLİĞİ", _f_kar_istikrarli),
    "yp_riski_dusuk":  ("Açık YP pozisyonu özkaynağın %25'ini aşmıyor", "Kur şokuna dayanıklılık — veri yoksa elemez", _f_yp_riski_dusuk),
    "borc_ozkaynak":   ("Borç/Özkaynak en kötü %25 elenir", "Kaldıraç kesitsel eşik", _f_borc_ozkaynak),
}


# ===================================================================== SIRALAMA
# (olcum) -> sayı. kucuk_iyi=True ise küçük olan önce gelir.

SIRALAMALAR = {
    "ucuz":        ("En ucuz (FD/FAVÖK)", lambda o: o.get("fd_favok"), True),
    "dusuk_borc":  ("En düşük borçluluk", lambda o: o.get("net_borc_favok"), True),
    "kaliteli":    ("En iyi tahakkuk kalitesi", lambda o: o.get("tahakkuk"), True),
    "buyuyen":     ("En hızlı gelir büyümesi", lambda o: o.get("gelir_buyume"), False),
    "momentumlu":  ("En güçlü 6 ay momentum", lambda o: o.get("mom6"), False),
    "buyuk":       ("En büyük piyasa değeri", lambda o: o.get("pd"), False),
    "reel_buyuyen":("En hızlı REEL gelir büyümesi", lambda o: o.get("gelir_buyume"), False),
    "marj_artan":  ("Marjı en çok genişleyen", lambda o: o.get("marj_trend"), False),
    "nakit_uretken":("En yüksek nakit getirisi (İşl. nakdi/PD)", lambda o: o.get("nakit_getirisi"), False),
    "istikrarli":  ("Kâr sürekliliği en yüksek", lambda o: o.get("kar_istikrar"), False),
    "ucuz_satis":  ("En ucuz (FD/Satış)", lambda o: o.get("fd_satis"), True),
    "karli":       ("En yüksek FAVÖK marjı", lambda o: (o["favok"] / o["gelir"]) if (o.get("favok") and o.get("gelir")) else None, False),
    "siralamasiz": ("Sıralama yok — hepsi eşit ağırlık", lambda o: 0, True),
}


# ===================================================================== KORUMA
# Portföy seviyesinde nakde geçme. (baglam) -> True ise O AY NAKİTTE kal.

def _g_yok(ctx):
    return False

def _g_endeks_ma(ctx):
    """XU100 kendi 200 günlük ortalamasının altındaysa nakde geç."""
    return ctx.get("xu_ma200") is not None and ctx["xu_ma200"] < 0

def _g_endeks_ma_uzun(ctx):
    """XU100 300 günlük ortalamasının altındaysa nakde geç — daha yavaş, daha az sinyal."""
    return ctx.get("xu_ma300") is not None and ctx["xu_ma300"] < 0

def _g_aday_yok(ctx):
    """Kurallar yeterli aday üretmiyorsa nakitte kal (boş slot mantığının sert hali)."""
    return ctx.get("aday_sayisi", 0) < ctx.get("min_aday", 3)

def _g_drawdown(ctx):
    """Portföy zirveden %15'ten fazla düştüyse nakde geç, ortalama üstüne dönene kadar bekle."""
    return ctx.get("portfoy_dd", 0) <= -15 and (ctx.get("xu_ma200") or 0) < 0


KORUMALAR = {
    "yok":            ("Nakde geçme yok", "Her ay tam yatırımda kal", _g_yok),
    "endeks_ma":      ("XU100 200g ortalama altındaysa nakit", "Ortam bozulunca çekil", _g_endeks_ma),
    "endeks_ma_uzun": ("XU100 300g ortalama altındaysa nakit", "Daha yavaş, daha az yanlış sinyal", _g_endeks_ma_uzun),
    "aday_yok":       ("Yeterli aday yoksa nakit", "Kural aday üretmiyorsa zorla alma", _g_aday_yok),
    "drawdown":       ("Portföy %15 düştü ve ortam bozuksa nakit", "Kademeli fren", _g_drawdown),
}


# ===================================================================== PANEL

def panel_kur(veri, baslangic=None, bitis=None, min_pd=None):
    """
    Bütün ölçümleri BİR KEZ hesaplar. Sonrası saf hesap.
    Döner: (kararlar, panel, gunler, fiyat, xu_ma)
      panel: {gun: {kod: olcum}}
    """
    fiyat, finansal, piyasa, sektor, sektor_ad, isim, karantina, tedbir = veri
    tarih_ix = {k: sorted(v) for k, v in fiyat.items()}

    hisse_sayisi = {}
    for kod, F in finansal.items():
        if F["donemler"]:
            v = KH.deger(F["veri"], "odenmis_sermaye", F["donemler"][-1], F["fmt"], F["ix"], F["ixc"])
            if v:
                hisse_sayisi[kod] = v

    bas = (baslangic or GT.BASLANGIC).isoformat()
    bit = (bitis or GT.BITIS).isoformat()
    gunler = [g for g in GT.islem_gunleri(fiyat) if bas <= g <= bit]
    kararlar = GT.ay_sonlari(gunler)

    mp = GT.MIN_PD if min_pd is None else min_pd
    panel = {}
    for g in kararlar:
        ev = GT.evren_kur(g, fiyat, tarih_ix, finansal, hisse_sayisi, karantina, mp, None, tedbir)
        for kod, o in ev.items():
            o["sektor"] = sektor.get(kod)
            o["sektor_ad"] = sektor_ad.get(kod)
            o["ad"] = isim.get(kod)
        panel[g] = ev

    # XU100 ortalama mesafesi (koruma kurallari icin)
    xu = {}
    xp = PANEL / "endeks_gecmis" / "XU100.json"
    if xp.exists():
        for r in json.loads(xp.read_text(encoding="utf-8")).get("seri", []):
            if r.get("kapanis"):
                xu[r["tarih"]] = r["kapanis"]
    xu_ma = {}
    xt = sorted(xu)
    for g in kararlar:
        onceki = [t for t in xt if t <= g]
        xu_ma[g] = {
            "ma200": GT.ort_mesafe(xu, onceki[-1], 200) if len(onceki) >= 200 else None,
            "ma300": GT.ort_mesafe(xu, onceki[-1], 300) if len(onceki) >= 300 else None,
        }
    return kararlar, panel, gunler, fiyat, xu_ma, xu


def esikleri_hesapla(ev, dilim=0.25, gun=None):
    """O karar gününün kesitsel eşikleri. Mutlak eşik YOK, hep dağılımdan."""
    def ust(alan, poz_sart=False):
        v = sorted(o[alan] for o in ev.values()
                   if o.get(alan) is not None and (not poz_sart or o[alan] > 0))
        return v[int(len(v) * (1 - dilim))] if len(v) >= 8 else None

    # degerleme: SEKTOR ICI esik
    sek = {}
    for o in ev.values():
        if o.get("fd_favok") and o["fd_favok"] > 0:
            sek.setdefault(o.get("sektor"), []).append(o["fd_favok"])
    sek_esik = {}
    for s, vals in sek.items():
        vals.sort()
        sek_esik[s] = vals[int(len(vals) * (1 - dilim))] if len(vals) >= 8 else None
    genel = sorted(o["fd_favok"] for o in ev.values() if o.get("fd_favok") and o["fd_favok"] > 0)
    genel_esik = genel[int(len(genel) * (1 - dilim))] if len(genel) >= 8 else None

    marjlar = sorted(o["favok_marj"] for o in ev.values() if o.get("favok_marj") is not None)
    marj_medyan = marjlar[len(marjlar) // 2] if len(marjlar) >= 8 else None

    return {
        "tufe": tufe_asof(gun) if gun else None,
        "marj_medyan": marj_medyan,
        "borc_ozk_esik": ust("borc_ozkaynak", poz_sart=True),
        "tahakkuk_esik": ust("tahakkuk"),
        "borc_esik": ust("net_borc_favok", poz_sart=True),
        "pddd_esik": ust("pd_dd", poz_sart=True),
        "deger_esik": None,          # sektör içi ayrı hesaplanır
        "_sektor_deger": sek_esik,
        "_genel_deger": genel_esik,
    }


# ===================================================================== SIMULASYON

def kombinasyon_calistir(kararlar, panel, gunler, fiyat, xu_ma,
                         suzgecler, siralama, koruma="yok",
                         pozisyon=10, sektor_tavani=3, min_aday=3):
    """
    Bir kural kombinasyonunu geçmişe dönük çalıştırır.
    T+1 uygulama, işlem maliyeti ve nakde geçme korumasıyla.
    Döner: sonuç sözlüğü (seri, ölçüt, işlem sayısı, nakit ayları...)
    """
    fnler = [SUZGECLER[k][2] for k in suzgecler if k in SUZGECLER]
    sira_fn, kucuk_iyi = SIRALAMALAR[siralama][1], SIRALAMALAR[siralama][2]
    guard = KORUMALAR.get(koruma, KORUMALAR["yok"])[2]

    nakit, poz = GT.BASLANGIC_SERMAYE, {}
    seri, islemler = [], []
    islem_sayisi, maliyet_top, nakit_ay = 0, 0.0, 0
    son_bilinen, bekleyen = {}, None
    zirve = GT.BASLANGIC_SERMAYE

    for gi, gun in enumerate(gunler):
        for kod, s in fiyat.items():
            if gun in s:
                son_bilinen[kod] = s[gun]

        # --- T+1: onceki karar gununun emri BUGUN uygulanir
        if bekleyen and bekleyen["gun"] != gun:
            secim = [k for k in bekleyen["secim"]
                     if fiyat.get(k, {}).get(gun) or son_bilinen.get(k)]
            deger = nakit + GT.portfoy_degeri(poz, gun, fiyat, son_bilinen)
            m = 0.0
            for kod, lot in poz.items():
                f = fiyat.get(kod, {}).get(gun) or son_bilinen.get(kod)
                if kod not in secim and f:
                    m += lot * f * GT.ISLEM_MALIYETI
                    islem_sayisi += 1
            if secim:
                hedef = deger / len(secim)
                for kod in secim:
                    f = fiyat.get(kod, {}).get(gun) or son_bilinen.get(kod)
                    eski = poz.get(kod, 0.0)
                    if eski == 0:
                        islem_sayisi += 1
                    m += abs(hedef / f - eski) * f * GT.ISLEM_MALIYETI
                deger -= m
                hedef = deger / len(secim)
                poz = {k: hedef / (fiyat.get(k, {}).get(gun) or son_bilinen[k]) for k in secim}
                nakit = 0.0
                islemler.append({"tarih": gun, "hisseler": sorted(secim)})
            else:                       # NAKDE GEC
                deger -= m
                poz, nakit = {}, deger
                nakit_ay += 1
                islemler.append({"tarih": gun, "hisseler": []})
            maliyet_top += m
            bekleyen = None

        # --- karar gunu: secimi YAP, emri kuyruga al
        if gun in kararlar:
            ev = panel.get(gun, {})
            esik = esikleri_hesapla(ev, gun=gun)
            aday = []
            for kod, o in ev.items():
                b = dict(esik)
                b["deger_esik"] = (esik["_sektor_deger"].get(o.get("sektor"))
                                   or esik["_genel_deger"])
                if all(fn(o, b) for fn in fnler):
                    aday.append((kod, o))

            deger_su_an = nakit + GT.portfoy_degeri(poz, gun, fiyat, son_bilinen)
            zirve = max(zirve, deger_su_an)
            ctx = {
                "xu_ma200": xu_ma.get(gun, {}).get("ma200"),
                "xu_ma300": xu_ma.get(gun, {}).get("ma300"),
                "aday_sayisi": len(aday),
                "min_aday": min_aday,
                "portfoy_dd": (deger_su_an / zirve - 1) * 100 if zirve else 0,
            }
            if guard(ctx):
                bekleyen = {"gun": gun, "secim": []}      # nakde gec
            else:
                puanli = [(k, sira_fn(o), o) for k, o in aday]
                puanli = [p for p in puanli if p[1] is not None]
                puanli.sort(key=lambda x: x[1], reverse=not kucuk_iyi)
                secim, sektor_say = [], {}
                for k, _, o in puanli:
                    s = o.get("sektor")
                    if sektor_tavani and sektor_say.get(s, 0) >= sektor_tavani:
                        continue        # SEKTOR TAVANI: tek sektore yiglima
                    secim.append(k)
                    sektor_say[s] = sektor_say.get(s, 0) + 1
                    if len(secim) >= pozisyon:
                        break
                bekleyen = {"gun": gun, "secim": secim}

        if gi % 5 == 0 or gun == gunler[-1]:
            v = nakit + GT.portfoy_degeri(poz, gun, fiyat, son_bilinen)
            seri.append({"tarih": gun, "deger": round(v, 2)})

    olcut = GT.olcut(seri)
    return {
        "suzgecler": list(suzgecler), "siralama": siralama, "koruma": koruma,
        "kural_sayisi": len(suzgecler) + 1 + (1 if koruma != "yok" else 0),
        "seri": seri, "olcut": olcut,
        "alt_donemler": GT.alt_donemler(seri),
        "islem_sayisi": islem_sayisi,
        "toplam_maliyet": round(maliyet_top),
        "nakit_ay": nakit_ay,
        "son_portfoy": islemler[-1]["hisseler"] if islemler else [],
    }


# ===================================================================== REJİM
#
# "Piyasanın açık olduğu dönem ile kapalı farklı sonuç verir" — doğru. Bir kural
# setinin ortalama getirisi, hangi ortamlarda çalıştığını gizler. Bu yüzden her
# kombinasyonun sonucu REJİMLERE göre de ayrıştırılır.
#
# Rejim, iki eksenden türetilir:
#   REEL FAİZ  = politika faizi − yıllık TÜFE      (pozitif / negatif)
#   FAİZ YÖNÜ  = son 6 ayda faiz değişimi          (sıkılaşma / gevşeme)
#
# Dört rejim, ikisi de kolay yorumlanır:
#   negatif_sikilasma : reel faiz eksi ama TCMB sıkıyor  → geçiş dönemi
#   negatif_gevseme   : reel faiz eksi, faiz düşüyor     → varlık enflasyonu ortamı
#   pozitif_sikilasma : reel faiz artı ve sıkılaşma      → en zorlu ortam
#   pozitif_gevseme   : reel faiz artı, faiz düşüyor     → normalleşme

REJIM_ADI = {
    "negatif_gevseme":   "Negatif reel faiz · gevşeme",
    "negatif_sikilasma": "Negatif reel faiz · sıkılaşma",
    "pozitif_gevseme":   "Pozitif reel faiz · gevşeme",
    "pozitif_sikilasma": "Pozitif reel faiz · sıkılaşma",
    "bilinmiyor":        "Veri yok",
}


def _aylik_seri(yol, anahtar=None):
    d = json.loads((PANEL / yol).read_text(encoding="utf-8"))
    s = d[anahtar] if anahtar else d.get("seri", [])
    return {r["tarih"]: r["deger"] for r in s if r.get("deger") is not None}


def rejim_serisi():
    """{YYYY-AA: {rejim, faiz, tufe_yillik, reel_faiz, faiz_degisim}}"""
    try:
        faiz = _aylik_seri("faiz_gecmis.json")
    except Exception:
        return {}
    try:
        tufe_ix = json.loads((PANEL / "deflator.json").read_text(encoding="utf-8"))
        tufe_ix = {r["tarih"]: r["deger"] for r in tufe_ix["deflatorler"]["tufe"]["seri"]
                   if r.get("deger")}
    except Exception:
        tufe_ix = {}

    def ay_ekle(ay, n):
        y, a = int(ay[:4]), int(ay[5:7])
        t = y * 12 + (a - 1) + n
        return f"{t // 12:04d}-{t % 12 + 1:02d}"

    cikti = {}
    for ay in sorted(set(faiz) | set(tufe_ix)):
        f = faiz.get(ay)
        ix_su, ix_gecen = tufe_ix.get(ay), tufe_ix.get(ay_ekle(ay, -12))
        yillik = ((ix_su / ix_gecen - 1) * 100) if (ix_su and ix_gecen) else None
        f6 = faiz.get(ay_ekle(ay, -6))
        degisim = (f - f6) if (f is not None and f6 is not None) else None
        if f is None or yillik is None or degisim is None:
            cikti[ay] = {"rejim": "bilinmiyor", "faiz": f, "tufe_yillik": yillik,
                         "reel_faiz": None, "faiz_degisim": degisim}
            continue
        reel = f - yillik
        r = ("pozitif" if reel > 0 else "negatif") + "_" + \
            ("sikilasma" if degisim > 0.5 else "gevseme")
        cikti[ay] = {"rejim": r, "faiz": round(f, 2),
                     "tufe_yillik": round(yillik, 2), "reel_faiz": round(reel, 2),
                     "faiz_degisim": round(degisim, 2)}
    return cikti


def rejim_bazinda_getiri(seri, rejimler):
    """Bir portföy serisini rejimlere göre parçalayıp her rejimdeki BİLEŞİK
    getiriyi ve o rejimde geçirilen ay sayısını verir."""
    gruplar = {}
    for i in range(1, len(seri)):
        ay = seri[i]["tarih"][:7]
        r = rejimler.get(ay, {}).get("rejim", "bilinmiyor")
        onceki, simdi = seri[i - 1]["deger"], seri[i]["deger"]
        if onceki:
            gruplar.setdefault(r, []).append(simdi / onceki)
    cikti = {}
    for r, oranlar in gruplar.items():
        birlesik = 1.0
        for o in oranlar:
            birlesik *= o
        # 5 gunluk orneklemden yillik bilesige cevir
        yil = len(oranlar) * 5 / 252
        cikti[r] = {
            "toplam_getiri": round((birlesik - 1) * 100, 1),
            "yillik_getiri": round((birlesik ** (1 / yil) - 1) * 100, 1) if yil > 0.25 else None,
            "gozlem": len(oranlar),
            "yaklasik_ay": round(len(oranlar) * 5 / 21, 1),
        }
    return cikti
