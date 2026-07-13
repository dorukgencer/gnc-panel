# -*- coding: utf-8 -*-
"""
GNC Insight - Rotasyon Saati icin GECMIS ZAMAN SERISI
Sektor Rotasyonu sayfasindaki kaydirma cubugu (slider) icin, son 52 haftanin
(1 yil) HER biri icin TUM sektorlerin (cx,cy,evre,yaricap) konumunu onceden
hesaplar. Kullanici cubugu kaydirdiginda, yeniden hesap yapmadan dogrudan bu
onceden-hesaplanmis anlik goruntuye "isinlanir".

rotasyon_hesapla.py'deki AYNI rank-tabanli koordinat mantigini kullanir (import
eder) - iki farkli hesaplama yontemi olmasin diye kod tekrari degil, dogrudan
paylasilan fonksiyonlar kullanilir.

ONEMLI: Her hafta icin rank hesabi O HAFTANIN KENDI capraz-kesit dagilimina
gore yapilir (bugunku dagilima gore degil) - boylece "2 ay once nasil
gorunuyordu" sorusuna o ANKI gercek goreli konumla cevap verilir.

Cikti: gnc-panel/rotasyon_zaman_serisi.json
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

KLASOR = Path(__file__).parent
sys.path.insert(0, str(KLASOR))
import rotasyon_hesapla as rh

HEDEF = KLASOR / "gnc-panel" / "rotasyon_zaman_serisi.json"
GOSTERILECEK_HAFTA_SAYISI = 52  # ~1 yil - cubugun kapsayacagi gecmis


def hafta_tarihine_cevir(hafta_tuple):
    yil, hafta_no = hafta_tuple
    try:
        return datetime.fromisocalendar(yil, hafta_no, 1).strftime("%Y-%m-%d")
    except Exception:
        return f"{yil}-W{hafta_no}"


def main():
    xu_ham = rh.seriyi_yukle("XU100")
    if not xu_ham:
        raise SystemExit("XU100 endeks_gecmis dosyasi bulunamadi.")
    xu_seri, _ = xu_ham
    xu_haftalik = rh.haftalik_kapanis(xu_seri)

    kodlar = rh.sektor_listesi()
    if not kodlar:
        raise SystemExit("Hicbir sektor endeks_gecmis dosyasi bulunamadi.")

    agirliklar, _ = rh.sektor_agirliklari()

    # Her sektor icin: {hafta_tarihi: (x, y)} sozlugu topla
    sektor_x_serileri = {}  # kod -> [(tarih, x), ...] kronolojik
    sektor_adlari = {}

    for kod in kodlar:
        yuklenen = rh.seriyi_yukle(kod)
        if not yuklenen:
            continue
        sek_seri, sek_ad = yuklenen
        sek_haftalik = rh.haftalik_kapanis(sek_seri)
        if len(sek_haftalik) < rh.X_PENCERE_HAFTA + rh.Y_PENCERE_HAFTA + 2:
            continue
        x_serisi = rh.x_serisi_hesapla(sek_haftalik, xu_haftalik)
        sektor_adlari[kod] = sek_ad

        liste = []
        for i in range(len(x_serisi)):
            if x_serisi[i] is None:
                continue
            tarih = hafta_tarihine_cevir(sek_haftalik[i]["hafta"])
            liste.append((tarih, x_serisi[i]))
        sektor_x_serileri[kod] = liste

    if not sektor_x_serileri:
        raise SystemExit("Hicbir sektor icin X serisi hesaplanamadi.")

    # Ortak tarih ekseni: TUM sektorlerde bulunan (yeterli gecmisi olan) haftalar
    tum_tarihler = sorted(set(t for liste in sektor_x_serileri.values() for t, _ in liste))
    # Son GOSTERILECEK_HAFTA_SAYISI kadarini al (+ Y_PENCERE_HAFTA kadar fazladan,
    # cunku momentum hesaplamak icin bir onceki 4 haftaya da erisim gerekiyor)
    gerekli_gecmis = GOSTERILECEK_HAFTA_SAYISI + rh.Y_PENCERE_HAFTA
    tarih_penceresi = tum_tarihler[-gerekli_gecmis:] if len(tum_tarihler) > gerekli_gecmis else tum_tarihler

    # Her sektor icin tarih->x haritasi (hizli erisim icin)
    sektor_x_harita = {kod: dict(liste) for kod, liste in sektor_x_serileri.items()}

    anlik_goruntuler = {}
    gosterilecek_tarihler = tarih_penceresi[rh.Y_PENCERE_HAFTA:]  # ilk Y_PENCERE_HAFTA'yi atla, momentum icin gerekliydi

    for idx, tarih in enumerate(gosterilecek_tarihler):
        gercek_idx = idx + rh.Y_PENCERE_HAFTA  # tarih_penceresi icindeki gercek konum
        onceki_tarih = tarih_penceresi[gercek_idx - rh.Y_PENCERE_HAFTA]

        # Bu haftanin TUM sektorler icin X ve Y degerlerini topla (rank hesabi icin sart)
        bu_hafta_x = {}
        bu_hafta_y = {}
        for kod, harita in sektor_x_harita.items():
            x_simdi = harita.get(tarih)
            x_once = harita.get(onceki_tarih)
            if x_simdi is not None and x_once is not None:
                bu_hafta_x[kod] = x_simdi
                bu_hafta_y[kod] = x_simdi - x_once

        if len(bu_hafta_x) < 3:
            continue  # bu haftada yeterli sektor verisi yok, atla

        tum_x_degerleri = list(bu_hafta_x.values())
        tum_y_degerleri = list(bu_hafta_y.values())

        anlik_goruntu = {}
        for kod in bu_hafta_x:
            x, y = bu_hafta_x[kod], bu_hafta_y[kod]
            cx, cy = rh.koordinat_hesapla_rank(x, y, tum_x_degerleri, tum_y_degerleri)
            evre = rh.evre_belirle(x, y)
            anlik_goruntu[kod] = {
                "ad": sektor_adlari.get(kod, kod),
                "cx": cx, "cy": cy, "evre": evre,
                "yaricap": rh.bubble_yaricap(agirliklar.get(kod)),
            }
        anlik_goruntuler[tarih] = anlik_goruntu

    if not anlik_goruntuler:
        raise SystemExit("Hicbir hafta icin anlik goruntu hesaplanamadi.")

    haftalar_sirali = sorted(anlik_goruntuler.keys())

    cikti = {
        "guncelleme": datetime.now(timezone.utc).isoformat(),
        "not": (
            "Rotasyon Saati'nin gecmis haftalardaki gorunumu - kaydirma cubugu icin "
            "onceden hesaplanmis anlik goruntuler. Her haftanin rank-tabanli koordinati "
            "O HAFTANIN KENDI capraz-kesit dagilimina gore hesaplanmistir (bugunku "
            "dagilima gore DEGIL) - boylece gecmisteki gercek goreli konum yansitilir."
        ),
        "haftalar": haftalar_sirali,
        "anlik_goruntuler": anlik_goruntuler,
    }
    HEDEF.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")

    print(f"Tamamlandi: {len(haftalar_sirali)} haftalik anlik goruntu -> {HEDEF}")
    print(f"  Ilk hafta: {haftalar_sirali[0]}, son hafta: {haftalar_sirali[-1]}")


if __name__ == "__main__":
    main()
