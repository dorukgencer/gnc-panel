# -*- coding: utf-8 -*-
"""
GNC Insight - Rotasyon Degisim Gunlugu GECMIS DOLDURMA (tek seferlik)

rotasyon_hesapla.py zaten HER sektor icin X(t) serisini BASTAN SONA (elimizdeki
tum haftalik gecmis boyunca) hesapliyor - sadece "bugunku" degeri kullaniliyordu.
Bu script AYNI hesabi yeniden yaparak (kod tekrari degil, DOGRUDAN import ederek)
GECMISTEKI her hafta icin evreyi turetir, hafta-hafta karsilastirip GERCEK
gecis olaylarini bulur ve rotasyon_degisim_log.json'u GERCEK veriyle doldurur.

Bu TEK SEFERLIK calisir. Calistirdiktan sonra normal haftalik
rotasyon_degisim_takip.py, bu script'in biraktigi son hafta anlik goruntusunden
(rotasyon_onceki_hafta.json) devam eder - cakisma olmaz.

NOT: Ilk ~17 hafta (13+4 pencere) evre hesaplanamaz (yeterli gecmis yok),
bu dogal bir sinir - uydurma veri retmiyoruz.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

KLASOR = Path(__file__).parent
sys.path.insert(0, str(KLASOR))
import rotasyon_hesapla as rh

LOG = KLASOR / "gnc-panel" / "rotasyon_degisim_log.json"
ONCEKI = KLASOR / "gnc-panel" / "rotasyon_onceki_hafta.json"

SABLON = {
    ("toparlanma", "genisleme"): "{ad} genişleme evresine geçti; BIST100'e göre görece gücü artık pozitif ve momentum güçlü.",
    ("daralma", "toparlanma"): "{ad} toparlanma evresine geçti; zayıflık sürüyor ama fark kapanmaya başladı.",
    ("genisleme", "yavaslama"): "{ad} yavaşlama evresine geçti; hâlâ BIST100'ü geçiyor ama momentum zayıflamaya başladı.",
    ("yavaslama", "daralma"): "{ad} daralma evresine geçti; hem göreli güç hem momentum negatif.",
}
GNC_EVRE_AD = {"genisleme": "Genişleme", "toparlanma": "Toparlanma", "yavaslama": "Yavaşlama", "daralma": "Daralma"}


def sablon_cumle(ad, onceki_evre, yeni_evre):
    s = SABLON.get((onceki_evre, yeni_evre))
    if s:
        return s.format(ad=ad)
    return f"{ad}, {GNC_EVRE_AD.get(onceki_evre,onceki_evre)} evresinden {GNC_EVRE_AD.get(yeni_evre,yeni_evre)} evresine geçti."


def hafta_tarihine_cevir(hafta_tuple):
    """(yil, hafta_no) ISO tuple'ini o haftanin Pazartesi tarihine cevirir."""
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

    tum_gecisler = []  # tum sektorlerin tum gecisleri, sonra tarihe gore siralanacak
    son_hafta_evreleri = {}  # en son haftanin evresi (onceki_hafta.json icin)
    en_son_tarih = None

    for kod in kodlar:
        yuklenen = rh.seriyi_yukle(kod)
        if not yuklenen:
            continue
        sek_seri, sek_ad = yuklenen
        sek_haftalik = rh.haftalik_kapanis(sek_seri)
        if len(sek_haftalik) < rh.X_PENCERE_HAFTA + rh.Y_PENCERE_HAFTA + 2:
            print(f"  {kod}: yetersiz gecmis, atlandi")
            continue

        x_serisi = rh.x_serisi_hesapla(sek_haftalik, xu_haftalik)

        # Her hafta icin (X ve Y hesaplanabiliyorsa) evreyi bul
        evre_dizisi = []  # [(hafta_tarihi, evre), ...] kronolojik
        for i in range(len(x_serisi)):
            if i - rh.Y_PENCERE_HAFTA < 0:
                continue
            x_simdi = x_serisi[i]
            x_4hf_once = x_serisi[i - rh.Y_PENCERE_HAFTA]
            if x_simdi is None or x_4hf_once is None:
                continue
            y_simdi = x_simdi - x_4hf_once
            evre = rh.evre_belirle(x_simdi, y_simdi)
            tarih = hafta_tarihine_cevir(sek_haftalik[i]["hafta"])
            evre_dizisi.append((tarih, evre))

        if not evre_dizisi:
            continue

        # Ardisik haftalar arasi GERCEK gecisleri bul
        son_degisim_tarihi = evre_dizisi[0][0]
        for j in range(1, len(evre_dizisi)):
            onceki_tarih, onceki_evre = evre_dizisi[j - 1]
            yeni_tarih, yeni_evre = evre_dizisi[j]
            if yeni_evre != onceki_evre:
                try:
                    gun_farki = (datetime.strptime(yeni_tarih, "%Y-%m-%d") - datetime.strptime(son_degisim_tarihi, "%Y-%m-%d")).days
                    hafta_farki = max(1, round(gun_farki / 7))
                    sure_metni = f"{hafta_farki} hafta"
                except Exception:
                    sure_metni = "bilinmiyor"
                tum_gecisler.append({
                    "tarih": yeni_tarih,
                    "kod": kod,
                    "ad": sek_ad,
                    "onceki_evre": onceki_evre,
                    "yeni_evre": yeni_evre,
                    "onceki_evrede_kalma_suresi": sure_metni,
                    "not": sablon_cumle(sek_ad, onceki_evre, yeni_evre),
                })
                son_degisim_tarihi = yeni_tarih

        son_hafta_evreleri[kod] = evre_dizisi[-1][1]
        if en_son_tarih is None or evre_dizisi[-1][0] > en_son_tarih:
            en_son_tarih = evre_dizisi[-1][0]

    if not tum_gecisler:
        raise SystemExit("Hicbir gecis bulunamadi - beklenmedik, veri yetersiz olabilir.")

    # En yeniden en eskiye sirala (sayfa boyle bekliyor)
    tum_gecisler.sort(key=lambda x: x["tarih"], reverse=True)
    tum_gecisler = tum_gecisler[:200]

    LOG.write_text(json.dumps({
        "guncelleme": datetime.now(timezone.utc).isoformat(),
        "not": (
            "Gecmis gecisler endeks_gecmis'teki gercek fiyat verisinden GERIYE DONUK "
            "hesaplanmistir (tek seferlik doldurma). Bundan sonraki gecisler haftalik "
            "olarak otomatik eklenir. 'not' alani sablon cumledir, elle zenginlestirilebilir."
        ),
        "kayitlar": tum_gecisler,
    }, ensure_ascii=False), encoding="utf-8")

    # Normal haftalik takipcinin devam edebilmesi icin "onceki hafta" anlik goruntusunu yaz
    ONCEKI.write_text(json.dumps({
        "tarih": en_son_tarih,
        "evreler": son_hafta_evreleri,
    }, ensure_ascii=False), encoding="utf-8")

    print(f"\nTamamlandi: {len(tum_gecisler)} gercek gecis bulundu -> {LOG}")
    print(f"En son hafta ({en_son_tarih}) anlik goruntusu -> {ONCEKI} (haftalik takipci buradan devam edecek)")
    for g in tum_gecisler[:10]:
        print(f"  {g['tarih']}  {g['kod']:8s} {g['onceki_evre']:12s} -> {g['yeni_evre']:12s} ({g['onceki_evrede_kalma_suresi']})")


if __name__ == "__main__":
    main()
