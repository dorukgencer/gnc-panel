# -*- coding: utf-8 -*-
"""
GNC Insight - Sektor Bazinda F/K Hesaplayici (guncel + 5 yillik ortalama)
Mevcut finansal/*.json ve hisse_gecmis/*.json dosyalarindan - YENI VERI
CEKMEDEN - sektor bazinda F/K hesaplar.

YONTEM: F/K = Fiyat / Hisse Basina Kazanc (EPS)
"Hisse Basina Kazanc" kalemi finansal tablolarda zaten cumulatif-yillik
(/12 donemi = tam yil EPS) olarak mevcut - bu sayede PD ve hisse sayisi
(bedelli/bedelsiz sermaye artirimlarindan etkilenen, elimizde tarihsel
verisi olmayan bir deger) hic gerekmiyor. Fiyat / EPS = F/K, direkt.

- Guncel F/K: guncel fiyat / en son acikanan yillik (/12) EPS
- 5 yillik ortalama: son 5 yilin her birinin Aralik-sonu fiyati / o yilin
  yillik EPS'i hesaplanir, 5 deger ortalanir
- Sektor F/K'si = sektordeki sirketlerin F/K medyanidir (asiri degerlerden
  etkilenmesin diye ortalama degil medyan - buyume_hesapla.py ile ayni mantik)
- Negatif/sifir EPS'li sirketler F/K hesabina katilmaz (anlamsiz sonuc verir)
"""

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

KLASOR = Path(__file__).parent
FINANSAL_KLASOR = KLASOR / "gnc-panel" / "finansal"
GECMIS_KLASOR = KLASOR / "gnc-panel" / "hisse_gecmis"
HEDEF = KLASOR / "gnc-panel" / "degerleme_gecmis.json"

EPS_KALEMI = "Hisse Başına Kazanç"
OZKAYNAK_KALEMI = "Özkaynaklar"
BANKA_OZKAYNAK_KALEMI = "XVI. ÖZKAYNAKLAR"
# PD/Satislar icin - F/K'nin aksine ZARAR eden sirketleri de KAPSAR (hasilat
# hemen hic negatif/sifir olmaz), F/K'deki "500 F/K vs 10 F/K" gibi asiri
# saciklik sorununu da yasamaz (kazanc kalemlerinden cok daha az oynak).
# Sektore gore isim degisebilir (banka vs sanayi) - birden fazla aday deneriz.
HASILAT_KALEM_ADAYLARI = ["Hasılat", "Satış Gelirleri", "Esas Faaliyet Gelirleri"]
# Net kar/zarar icin - ADIM ADIM DOGRULANMIS BOLUNME DUZELTMESI icin sart:
# ayni sirketin FARKLI kaynaklarinda bile bu kalemin adi degisebiliyor (KAP
# gelir tablosunda "Net Dönem Kârı (Zararı)", bilanço/özkaynak bölümünde
# "Dönem Net Kar/Zararı" gördük - 13 Tem 2026'da TRALT ornekleriyle
# dogrulandi). Birden fazla aday deniyoruz, HASILAT_KALEM_ADAYLARI'ndaki
# ayni mantik.
NET_KAR_KALEM_ADAYLARI = ["Net Dönem Kârı (Zararı)", "Dönem Net Kar/Zararı", "Net Dönem Karı", "Dönem Kârı (Zararı)", "Net Dönem Karı (Zararı)"]


def tufe_yillik_endeks():
    """deflator.json'daki HAM TUFE endeks serisinden (reel_getiri_cek.py'nin
    zaten urettigi, TP.FG.J0/2003=100) her yilin ARALIK ayi endeks degerini
    cikarir -> {"2016": 412.3, ..., "2025": 2891.7} gibi.
    Bu, Shiller CAPE mantiginin (her yilin karini TUFE ile BUGUNE tasiyip
    OYLE ortalamak) temelini olusturur - "2023 oncesine hic gitme" gibi kaba
    bir sinir yerine, enflasyonun kendisini duzeltiyoruz.
    NOT: Bu SADECE enflasyon karsilastirilabilirligini duzeltir - eger bir
    sirkette AYRICA bedelsiz sermaye artirimi (hisse bolunmesi) da olduysa
    (TRALT'ta gordugumuz ~20 kat EPS sicramasi gibi), TUFE duzeltmesi TEK
    BASINA bunu COZMEZ - o ayri bir mekanizma (bolunme tespiti) gerektirir,
    burada YOK."""
    try:
        veri = json.loads((KLASOR / "gnc-panel" / "deflator.json").read_text(encoding="utf-8"))
        seri = veri.get("deflatorler", {}).get("tufe", {}).get("seri", [])
    except Exception:
        return {}
    if not seri:
        return {}
    yillik = {}
    for nokta in seri:
        tarih = nokta.get("tarih", "")
        deger = nokta.get("deger")
        if deger is None or "-" not in tarih:
            continue
        yil, ay = tarih.split("-")[0], tarih.split("-")[1]
        if ay == "12":
            yillik[yil] = deger
        elif yil not in yillik:
            # o yilin Aralik'i yoksa (henuz aciklanmadiysa - orn. cari yil),
            # o yil icin bulunan EN SON ayi gecici olarak kullan.
            yillik[yil] = deger
    return yillik


def deflator_hesapla(tufe_endeksleri, hedef_yil, baz_yil):
    """hedef_yil'deki 1 TL'nin, baz_yil (genelde en yeni yil) TL'si
    cinsinden karsiligini dondurur. Ornek: 2020'de kazanilan 1 TL, eger
    TUFE 2020'den 2025'e 6 kat arttiysa, 2025 TL'si cinsinden ~6 TL eder."""
    tufe_hedef = tufe_endeksleri.get(hedef_yil)
    tufe_baz = tufe_endeksleri.get(baz_yil)
    if not tufe_hedef or not tufe_baz:
        return None
    return tufe_baz / tufe_hedef


def banka_kodlari():
    try:
        veri = json.loads((KLASOR / "gnc-panel" / "sektor_hisseler.json").read_text(encoding="utf-8"))
        return {h["kod"] for h in veri.get("hisseler", {}).get("XBANK", [])}
    except Exception:
        return set()


def pd_haritasi():
    """sektor_hisse_veri.json'dan (piyasa_cek.py ciktisi) guncel piyasa degeri haritasi."""
    try:
        veri = json.loads((KLASOR / "gnc-panel" / "sektor_hisse_veri.json").read_text(encoding="utf-8"))
        harita = {}
        for kod, v in veri.get("hisseler", {}).items():
            if isinstance(v, dict) and v.get("pd"):
                harita[kod] = v["pd"]
        return harita
    except Exception:
        return {}


def son_ozkaynak(kalemler, banka_mi):
    """En son ACIKLANAN (herhangi bir ceyrek olabilir - bilanço kalemi, yillik
    normalizasyon gerekmez) ozkaynak degerini doner.
    DIKKAT: donem stringleri ('2025/12' vs '2025/9') DUZ METIN olarak
    siralanamaz - '9' karakteri '12'den buyuk gorunur, yanlis sonuc verir.
    (yil,ay) TUPLE'ina cevirip oyle siraliyoruz."""
    ad = BANKA_OZKAYNAK_KALEMI if banka_mi else OZKAYNAK_KALEMI
    degerler = kalem_bul(kalemler, ad)
    if not degerler:
        return None
    gecerli = {d: v for d, v in degerler.items() if v is not None}
    if not gecerli:
        return None
    def donem_anahtari(d):
        yil, ay = d.split("/")
        return (int(yil), int(ay))
    son_donem = sorted(gecerli.keys(), key=donem_anahtari, reverse=True)[0]
    return gecerli[son_donem]


def sektor_haritasi():
    try:
        veri = json.loads((KLASOR / "gnc-panel" / "sektor_hisseler.json").read_text(encoding="utf-8"))
        harita = {}
        for sektor_kod, hisseler in veri.get("hisseler", {}).items():
            for h in hisseler:
                harita[h["kod"]] = sektor_kod
        return harita
    except Exception:
        return {}


def kalem_bul(kalemler, ad):
    for k in kalemler:
        if k.get("ad") == ad:
            return k.get("degerler", {})
    return None


def yillik_donemler(degerler):
    yillik = {d: v for d, v in degerler.items() if d.endswith("/12") and v is not None}
    return sorted(yillik.items(), key=lambda x: x[0], reverse=True)


def net_kar_yillik(kalemler):
    """NET_KAR_KALEM_ADAYLARI'ndan ilk BULUNAN kalemin TUM yillik (/12)
    serisini doner - yillik_donemler ile ayni format: [(donem, deger), ...]
    yeniden eskiye. Bolunme duzeltmesi icin gerekli: net kar (TOPLAM), EPS'in
    aksine hisse sayisi degisikliginden ETKILENMEZ - bu yuzden "gecmis yilin
    net karini BUGUNKU hisse sayisina bolersek" hisse bolunmesi otomatik
    duzelir, ayrica tespit/hariç tutma gerekmez."""
    for aday in NET_KAR_KALEM_ADAYLARI:
        degerler = kalem_bul(kalemler, aday)
        if degerler:
            yillik = yillik_donemler(degerler)
            if yillik:
                return yillik
    return []


def son_yillik_hasilat(kalemler):
    """EPS ile AYNI mantik: en son ACIKLANAN YILLIK (/12) hasilat donemi.
    Ceyreklik degil yillik kullaniyoruz ki mevsimsellik (bir sektorun Q4'u
    hep guclu olabilir mesela) F/K ile ayni tutarlilikta karsilastirilsin."""
    for aday in HASILAT_KALEM_ADAYLARI:
        degerler = kalem_bul(kalemler, aday)
        if degerler:
            yillik = yillik_donemler(degerler)
            if yillik:
                return yillik[0][1]  # en yeni yillik donemin degeri
    return None


def fiyat_serisi_yukle(kod):
    yol = GECMIS_KLASOR / f"{kod}.json"
    if not yol.exists():
        return None, {}
    try:
        veri = json.loads(yol.read_text(encoding="utf-8"))
    except Exception:
        return None, {}
    seri = sorted(veri.get("seri", []), key=lambda s: s["tarih"])
    if not seri:
        return None, {}
    guncel = seri[-1]["kapanis"]
    yil_sonu_fiyat = {}
    for s in seri:
        yil, ay = s["tarih"][:4], s["tarih"][5:7]
        if ay == "12":
            yil_sonu_fiyat[yil] = s["kapanis"]
    return guncel, yil_sonu_fiyat


def main():
    if not FINANSAL_KLASOR.exists() or not GECMIS_KLASOR.exists():
        raise SystemExit("finansal/ veya hisse_gecmis/ klasoru bulunamadi. Once ilgili pipeline'lar calismis olmali.")

    sektor_map = sektor_haritasi()
    if not sektor_map:
        raise SystemExit("sektor_hisseler.json okunamadi, sektor eslemesi yapilamiyor.")

    dosyalar = list(FINANSAL_KLASOR.glob("*.json"))
    print(f"{len(dosyalar)} sirket finansal dosyasi bulundu.")

    sektor_fk_guncel = {}
    sektor_fk_5yil = {}
    sektor_pd_dd = {}
    sektor_pd_satis = {}
    guncel_islenen = 0
    besyil_islenen = 0
    pd_dd_islenen = 0
    pd_satis_islenen = 0
    pd_harita = pd_haritasi()
    bankalar = banka_kodlari()
    tum_sektor_kodlari = set()          # sektor haritasinda GORULEN her sektor (veri olsun olmasin)
    negatif_epsli_sirket_sayisi = {}    # sektor -> kac sirket zarar ediyor (aciklama icin)
    supheli_bolunmeler = []             # KALICI liste - bolunme supheli sirketler, sadece log'da kaybolmasin

    # TUFE ile REEL (enflasyondan arindirilmis) tarihsel F/K - Shiller CAPE
    # mantigi. tufe_endeksleri bos donerse (deflator.json henuz yoksa) eski
    # (2023 siniri) yontem otomatik devreye girer - pipeline kirilmaz.
    tufe_endeksleri = tufe_yillik_endeks()
    tufe_baz_yil = max(tufe_endeksleri.keys()) if tufe_endeksleri else None
    if tufe_baz_yil:
        print(f"TUFE ile reel F/K duzeltmesi aktif, baz yil: {tufe_baz_yil}")
    else:
        print("UYARI: deflator.json'dan TUFE okunamadi - reel duzeltme YAPILAMIYOR, eski (2023 siniri) yontem kullanilacak.")

    for dosya in dosyalar:
        kod = dosya.stem
        sektor = sektor_map.get(kod)
        if not sektor:
            continue
        tum_sektor_kodlari.add(sektor)
        try:
            veri = json.loads(dosya.read_text(encoding="utf-8"))
        except Exception:
            continue
        kalemler = veri.get("kalemler", [])
        eps_degerler = kalem_bul(kalemler, EPS_KALEMI)
        if not eps_degerler:
            continue
        eps_yillik = yillik_donemler(eps_degerler)
        if not eps_yillik:
            continue

        guncel_fiyat, yil_sonu_fiyat = fiyat_serisi_yukle(kod)
        if guncel_fiyat is None:
            continue

        son_donem, son_eps = eps_yillik[0]

        # DUZELTME (13 Tem 2026, UCUNCU VERSIYON): THYAO ornegiyle bulundu -
        # buyuk sirketlerde raporlanan "Hisse Basina Kazanc" TAM SAYIYA
        # yuvarlaniyor olabilir (THYAO'da neredeyse her donem "0.0" gorunuyor,
        # oysa gercek net kari 130 MİLYAR TL - gercek EPS ~94 TL olmali, test
        # edildi). Bu, sadece TARIHSEL karsilastirmayi degil GUNCEL F/K'yi de
        # bozar. SAGLAM COZUM: hisse sayisini EPS'e hic bagimli olmadan,
        # dogrudan "Odenmis Sermaye"den al (Turkiye'de nominal deger neredeyse
        # evrensel olarak 1 TL) - bu alan HER ZAMAN tam hassasiyetle raporlanir.
        # Sonra GUNCEL EPS'i de (raporlanan degeri degil) net_kar/hisse_sayisi
        # olarak YENIDEN INSA edip kullaniyoruz - hem guncel hem tarihsel F/K
        # icin AYNI, daha guvenilir EPS kaynagi.
        odenmis_sermaye_serisi = kalem_bul(kalemler, "Ödenmiş Sermaye")
        guncel_hisse_sayisi = None
        if odenmis_sermaye_serisi:
            gecerli_sermaye = {d: v for d, v in odenmis_sermaye_serisi.items() if v}
            if gecerli_sermaye:
                def _donem_anahtari(d):
                    yil, ay = d.split("/")
                    return (int(yil), int(ay))
                son_sermaye_donem = sorted(gecerli_sermaye.keys(), key=_donem_anahtari, reverse=True)[0]
                guncel_hisse_sayisi = gecerli_sermaye[son_sermaye_donem]  # 1 TL nominal varsayimiyla = hisse sayisi

        net_kar_serisi = net_kar_yillik(kalemler)
        net_kar_harita = dict(net_kar_serisi)
        guncel_net_kar = net_kar_harita.get(son_donem)

        if not guncel_hisse_sayisi and guncel_net_kar and son_eps and son_eps > 0:
            # YEDEK: Odenmis Sermaye yoksa/gecersizse, eski yonteme don
            guncel_hisse_sayisi = guncel_net_kar / son_eps

        # Guncel F/K icin: raporlanan son_eps yerine, mumkunse YENIDEN INSA
        # EDILMIS (net_kar/hisse_sayisi) EPS'i tercih ediyoruz - THYAO gibi
        # buyuk sirketlerde raporlanan deger yuvarlanmis/guvenilmez olabilir.
        etkin_son_eps = son_eps
        if guncel_hisse_sayisi and guncel_net_kar:
            etkin_son_eps = guncel_net_kar / guncel_hisse_sayisi

        if etkin_son_eps and etkin_son_eps > 0:
            fk = guncel_fiyat / etkin_son_eps
            if 0 < fk < 150:
                sektor_fk_guncel.setdefault(sektor, []).append(fk)
                guncel_islenen += 1
        elif etkin_son_eps is not None and etkin_son_eps <= 0:
            negatif_epsli_sirket_sayisi[sektor] = negatif_epsli_sirket_sayisi.get(sektor, 0) + 1

        real_eps_listesi = []
        if guncel_hisse_sayisi and guncel_hisse_sayisi > 0:
            if guncel_net_kar is None:
                print(f"  {kod} ({sektor}): Net Dönem Kârı kalemi bulunamadı (aday isimler eşleşmedi)")
                supheli_bolunmeler.append({
                    "kod": kod, "sektor": sektor,
                    "not": "Net Dönem Kârı kalemi bulunamadı (aday isimler eşleşmedi) - hisse-sayısı normalizasyonu yapılamadı.",
                })
            else:
                for donem, eps in eps_yillik:
                    yil = donem[:4]
                    net_kar_o_yil = net_kar_harita.get(donem)
                    if net_kar_o_yil is None:
                        continue  # o yil icin net kar verisi yoksa (kalem adi eslesmedi vs) atla
                    normalize_eps = net_kar_o_yil / guncel_hisse_sayisi
                    if normalize_eps <= 0:
                        continue  # o yil zarar - F/K'ye katilmaz (mevcut kuralla tutarli)
                    if tufe_baz_yil:
                        deflator = deflator_hesapla(tufe_endeksleri, yil, tufe_baz_yil)
                        if deflator:
                            real_eps_listesi.append(normalize_eps * deflator)
                    elif yil >= "2023":
                        # TUFE yoksa eski (2023 siniri, duzeltmesiz) yonteme don -
                        # ama YINE DE hisse-sayisi normalizasyonu uygulanmis halde
                        real_eps_listesi.append(normalize_eps)
        else:
            print(f"  {kod} ({sektor}): hisse sayısı hesaplanamadı (Ödenmiş Sermaye alanı yok/geçersiz VE net kâr/EPS'ten türetme de başarısız) - tarihsel karşılaştırmaya KATILAMIYOR")
            supheli_bolunmeler.append({
                "kod": kod, "sektor": sektor,
                "not": "Hisse sayısı hesaplanamadı (Ödenmiş Sermaye alanı yok/geçersiz ve yedek türetme de başarısız).",
            })

        if len(real_eps_listesi) >= 2 and guncel_fiyat:
            ortalama_reel_eps = statistics.median(real_eps_listesi)
            cape_fk = guncel_fiyat / ortalama_reel_eps
            if 0 < cape_fk < 150:
                yillik_fk_listesi = [cape_fk]
            else:
                yillik_fk_listesi = []
        else:
            yillik_fk_listesi = []

        if len(yillik_fk_listesi) >= 1:
            # DUZELTME (13 Tem 2026): artik CAPE zaten TEK bir deger (sirketin
            # kendi coklu-yil REEL EPS ortalamasindan turetilen TEK F/K) -
            # ayrica ortalama/medyan almaya gerek yok, dogrudan sektor listesine ekleniyor.
            sirket_ortalama = yillik_fk_listesi[0]
            sektor_fk_5yil.setdefault(sektor, []).append(sirket_ortalama)
            besyil_islenen += 1

        # PD/DD = Piyasa Degeri / Ozkaynaklar (en son aciklanan donem, /12 olma sarti yok)
        pd_guncel = pd_harita.get(kod)
        ozkaynak = son_ozkaynak(kalemler, kod in bankalar)
        if pd_guncel and ozkaynak and ozkaynak > 0:
            pddd = pd_guncel / ozkaynak
            if 0 < pddd < 100:
                sektor_pd_dd.setdefault(sektor, []).append(pddd)
                pd_dd_islenen += 1

        # PD/Satislar = Piyasa Degeri / Hasilat - F/K'nin aksine ZARAR eden
        # sirketleri de KAPSAR (hasilat kazanc gibi sifira/negatife dusmez),
        # F/K'deki asiri saciklik sorununu da cok daha az yasar. son_eps'in
        # pozitif olma sarti YOK - bu metrigin butun amaci bu.
        hasilat = son_yillik_hasilat(kalemler)
        if pd_guncel and hasilat and hasilat > 0:
            pd_satis = pd_guncel / hasilat
            if 0 < pd_satis < 100:
                sektor_pd_satis.setdefault(sektor, []).append(pd_satis)
                pd_satis_islenen += 1

    if not sektor_fk_guncel and not sektor_pd_dd and not sektor_pd_satis:
        raise SystemExit("Hicbir sektor icin HICBIR metrik (F/K, PD/DD, PD/Satislar) hesaplanamadi. Kalem adlari degismis olabilir.")

    sonuc = {}
    # ONEMLI: sadece F/K hesaplanabilen sektorler degil, sektor haritasinda GORULEN
    # TUM sektorler dolasilir - boylece "tum sirketleri zarar eden" bir sektor
    # sessizce kaybolmaz, acikca "hesaplanamiyor" diye gorunur.
    for sektor in tum_sektor_kodlari:
        guncel_liste = sektor_fk_guncel.get(sektor, [])
        besyil_liste = sektor_fk_5yil.get(sektor, [])
        pddd_liste = sektor_pd_dd.get(sektor, [])
        pd_satis_liste = sektor_pd_satis.get(sektor, [])

        if len(guncel_liste) < 1:
            zarar_sayisi = negatif_epsli_sirket_sayisi.get(sektor, 0)
            girdi = {
                "fk_guncel_medyan": None,
                "sirket_sayisi_guncel": 0,
                "hesaplanamiyor_nedeni": (
                    f"Bu sektördeki {zarar_sayisi} şirket şu an zarar ediyor, pozitif kârlı şirket yok."
                    if zarar_sayisi > 0 else "Bu sektör için finansal veri henüz yok."
                ),
            }
            # ONEMLI: F/K hesaplanamasa bile PD/DD ve PD/Satislar HALA
            # hesaplanabilir olabilir - ikisi de zarar eden sirketleri
            # KAPSAR, bu yuzden ayni "continue" ile atlanmamali.
            if len(pddd_liste) >= 1:
                girdi["pd_dd_medyan"] = round(statistics.median(pddd_liste), 2)
            if len(pd_satis_liste) >= 1:
                girdi["pd_satis_medyan"] = round(statistics.median(pd_satis_liste), 2)
            sonuc[sektor] = girdi
            continue

        girdi = {
            "fk_guncel_medyan": round(statistics.median(guncel_liste), 2),
            "sirket_sayisi_guncel": len(guncel_liste),
            "guven_dusuk": len(guncel_liste) < 3,  # az sirketle hesaplanmis, sayfada isaretlenmeli
        }
        # DUZELTME (13 Tem 2026): esik >=1'den >=3'e yukseltildi. TMS 29 sinirindan
        # oturu elimizde sadece 2-3 "temiz" yil var - bu zaten kisa bir pencere;
        # USTUNE 1-2 sirketle hesaplanmis bir "tarihsel ortalama" istatistiksel
        # olarak guvenilir DEGIL, sadece guvenilir GORUNUYOR (kesin yuzde
        # bicimindeki). Az veriyle "veri yetersiz" demek, az veriyle yanlis
        # kesinlik iddia etmekten daha DURUST.
        if len(besyil_liste) >= 3:
            girdi["fk_5yil_ortalama_medyan"] = round(statistics.median(besyil_liste), 2)
            girdi["sirket_sayisi_5yil"] = len(besyil_liste)
            sapma = round((girdi["fk_guncel_medyan"] - girdi["fk_5yil_ortalama_medyan"]) / girdi["fk_5yil_ortalama_medyan"] * 100, 1)
            girdi["sapma_yuzde"] = sapma
            # DUZELTME: kesin yuzde yerine (ya da yaninda) KABA bir bant da
            # veriyoruz. Veri sadece 2-3 yillik oldugu icin "+61.9%" gibi tek
            # ondalikli bir kesinlik iddia etmek gercekci degil - "Pahali"
            # demek, veri buna yeter ama "%61.9 pahali" demek yetmez.
            if sapma <= -30:
                girdi["bant"] = "ucuz"
            elif sapma >= 30:
                girdi["bant"] = "pahali"
            else:
                girdi["bant"] = "notr"
        if len(pddd_liste) >= 1:
            girdi["pd_dd_medyan"] = round(statistics.median(pddd_liste), 2)
        if len(pd_satis_liste) >= 1:
            girdi["pd_satis_medyan"] = round(statistics.median(pd_satis_liste), 2)
        sonuc[sektor] = girdi

    cikti = {
        "guncelleme": datetime.now(timezone.utc).isoformat(),
        "durum": "deneysel",
        "not": (
            "DENEYSEL/BETA: Hem güncel hem tarihsel F/K, üç kademeli düzeltmeyle hesaplanıyor. "
            "1) HİSSE SAYISI: Ödenmiş Sermaye'den alınır (Türkiye'de nominal değer neredeyse "
            "evrensel olarak 1 TL). Bazı büyük şirketlerde (örn. THYAO) kaynağın raporladığı "
            "\"Hisse Başına Kazanç\" tam sayıya yuvarlanıp neredeyse hep \"0\" görünebiliyor - "
            "bu yüzden hisse sayısını EPS'e bağımlı olmadan, doğrudan Ödenmiş Sermaye'den alıyoruz. "
            "2) GÜNCEL VE TARİHSEL EPS: raporlanan (bazen yuvarlanmış) EPS yerine, her yılın "
            "TOPLAM Net Dönem Kârı bu hisse sayısına bölünerek YENİDEN HESAPLANIR - hem daha "
            "hassas hem de geçmişte kaç kez bedelsiz sermaye artırımı/hisse bölünmesi olduysa "
            "olsun otomatik düzelir, şüpheli şirketleri DIŞLAMIYORUZ (test edildi: THYAO'da "
            "kaynağın \"0\" gösterdiği EPS, gerçekte ~94 TL çıktı). "
            "3) TÜFE İLE REEL DEĞER (Shiller CAPE): normalize edilmiş EPS'ler TÜFE ile bugünün "
            "TL'sine taşınır (TP.FG.J0), şirketin kendi yılları arasındaki medyanı alınır, bugünkü "
            "fiyat bu medyana bölünür - S&P 500 için Robert Shiller'ın kullandığı yöntemin aynısı. "
            "Bu adımlar sayesinde 2023 öncesine de gidilebiliyor (sabit yıl sınırı yok). "
            "Net Dönem Kârı kalemi bulunamayan (adı eşleşmeyen) şirketler bu karşılaştırmaya "
            "katılamaz - bu, veri eksikliğidir, aykırı değer dışlaması değildir. "
            "Kesin yüzde yerine kaba bir bant (Ucuz/Nötr/Pahalı, ±%30 eşiğiyle) esas alınmalıdır; "
            "yüzdenin kendisi referans amaçlıdır, tek başına hassas bir ölçüm olarak okunmamalıdır. "
            "F/K = Fiyat / Hisse Başına Kazanç (EPS), en son açıklanan YILLIK (/12) dönem kullanılır. "
            "PD/DD = Piyasa Değeri / Özkaynaklar, en son açıklanan (herhangi bir çeyrek) dönem kullanılır. "
            "PD/Satışlar = Piyasa Değeri / en son açıklanan YILLIK Hasılat. F/K ve PD/DD'nin aksine "
            "zarar eden şirketleri de kapsar (hasılat kâr gibi sıfıra/negatife düşmez) ve F/K'nin "
            "yaşadığı aşırı saçıklığı (bir şirket F/K 10, diğeri F/K 500 gibi) çok daha az yaşar - "
            "F/K hesaplanamayan sektörlerde bile PD/DD ve PD/Satışlar hâlâ dolu olabilir. "
            "Sektör değerleri, sektördeki şirketlerin medyanıdır. Negatif/sıfır kârlı şirketler F/K'ye "
            "dahil edilmez. Tarihsel ortalama SADECE en az 3 şirketle hesaplanabiliyorsa gösterilir "
            "(2 şirketle 'medyan' istatistiksel olarak neredeyse ortalamaya eşitleşir, aykırı değere "
            "karşı korumasız kalır). "
            "Sapma % = (güncel F/K - CAPE F/K) / CAPE F/K × 100. "
            "Tek başına alım-satım sinyali değildir, eğitim ve araştırma amaçlıdır."
        ),
        "sektorler": sonuc,
        "supheli_bolunmeler": supheli_bolunmeler,
    }
    HEDEF.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")

    print(f"\nTamamlandi: {len(sonuc)} sektor -> {HEDEF}")
    print(f"  Guncel F/K icin islenen sirket: {guncel_islenen}, 5-yillik icin: {besyil_islenen}, PD/DD icin: {pd_dd_islenen}, PD/Satislar icin: {pd_satis_islenen}")
    if supheli_bolunmeler:
        print(f"  UYARI: {len(supheli_bolunmeler)} sirket bolunme supheliyle dislandi (detaylar degerleme_gecmis.json'da 'supheli_bolunmeler' alaninda ve panelde gorunur olacak)")
    for sek, veri in sorted(sonuc.items(), key=lambda x: (x[1]["fk_guncel_medyan"] is None, x[1]["fk_guncel_medyan"] or 0)):
        if veri["fk_guncel_medyan"] is None:
            print(f"  {sek:8s} F/K=HESAPLANAMIYOR ({veri.get('hesaplanamiyor_nedeni','-')})")
            continue
        sapma = veri.get("sapma_yuzde")
        pddd = veri.get("pd_dd_medyan")
        sapma_str = f" sapma=%{sapma:+.1f}" if sapma is not None else " (5y veri yetersiz)"
        pddd_str = f" PD/DD={pddd}" if pddd is not None else " (PD/DD veri yetersiz)"
        print(f"  {sek:8s} F/K={veri['fk_guncel_medyan']:6.1f}{sapma_str}{pddd_str}")


if __name__ == "__main__":
    main()
