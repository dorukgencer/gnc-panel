# -*- coding: utf-8 -*-
"""
GNC Insight - Rotasyon Degisim Takipcisi
rotasyon_hesapla.py HER HAFTA calisip rotasyon_gecmis.json'u YENIDEN YAZAR
(sadece o haftanin anlik durumunu tutar, gecmisi SAKLAMAZ). Bu script ise
her calismada: (1) bu haftanin evrelerini onceki haftayla KARSILASTIRIR,
(2) evre degisen sektorleri gunluge EKLER (rotasyon_degisim_log.json,
kalici, buyuyen bir liste), (3) bu haftanin evre "anlik goruntusunu" bir
sonraki hafta kiyaslamak icin ayri sakla (rotasyon_onceki_hafta.json).

Bu script rotasyon_hesapla.py'DEN SONRA calismali (ayni workflow, sonraki adim).

Not: Ilk calistirmada (onceki_hafta dosyasi yoksa) hicbir "degisim"
loglanmaz - sadece bu haftanin durumu "onceki" olarak kaydedilir. Yani
Degisim Gunlugu, EN ERKEN bu scriptin IKINCI calismasindan (bir hafta
sonra) itibaren gercek veri icerecektir. Bu, gecmisi olmayan bir seyi
uydurmamak icin BILINCLI bir tasarim kararidir.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

KLASOR = Path(__file__).parent
ROTASYON = KLASOR / "gnc-panel" / "rotasyon_gecmis.json"
ONCEKI = KLASOR / "gnc-panel" / "rotasyon_onceki_hafta.json"
LOG = KLASOR / "gnc-panel" / "rotasyon_degisim_log.json"

# Basit sablon cumleler - editoryal not yerine otomatik uretilir.
# Sartnamedeki oneri: "basta sablon cumle, ileride elle zenginlestirme."
SABLON = {
    ("toparlanma", "genisleme"): "{ad} genişleme evresine geçti; BIST100'e göre görece gücü artık pozitif ve momentum güçlü.",
    ("daralma", "toparlanma"): "{ad} toparlanma evresine geçti; zayıflık sürüyor ama fark kapanmaya başladı.",
    ("genisleme", "yavaslama"): "{ad} yavaşlama evresine geçti; hâlâ BIST100'ü geçiyor ama momentum zayıflamaya başladı.",
    ("yavaslama", "daralma"): "{ad} daralma evresine geçti; hem göreli güç hem momentum negatif.",
}
SABLON_VARSAYILAN = "{ad}, {onceki_ad} evresinden {yeni_ad} evresine geçti."


def sablon_cumle(ad, onceki_evre, yeni_evre):
    sablon = SABLON.get((onceki_evre, yeni_evre))
    if sablon:
        return sablon.format(ad=ad)
    return SABLON_VARSAYILAN.format(ad=ad, onceki_ad=GNC_EVRE_AD(onceki_evre), yeni_ad=GNC_EVRE_AD(yeni_evre))


def GNC_EVRE_AD(kod):
    return {"genisleme": "Genişleme", "toparlanma": "Toparlanma", "yavaslama": "Yavaşlama", "daralma": "Daralma"}.get(kod, kod)


def main():
    if not ROTASYON.exists():
        raise SystemExit(f"{ROTASYON} bulunamadi. Once rotasyon_hesapla.py calismis olmali.")

    guncel = json.loads(ROTASYON.read_text(encoding="utf-8"))
    guncel_sektorler = {s["kod"]: s for s in guncel.get("sektorler", [])}
    bugun = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if not ONCEKI.exists():
        print("Onceki hafta kaydi yok (ilk calistirma). Karsilastirma yapilamiyor, sadece bu haftanin")
        print("durumu 'onceki' olarak kaydediliyor. Degisim Gunlugu bir hafta sonra veri icermeye baslar.")
        onceki_kayit = {"tarih": bugun, "evreler": {k: v["evre"] for k, v in guncel_sektorler.items()}}
        ONCEKI.write_text(json.dumps(onceki_kayit, ensure_ascii=False), encoding="utf-8")
        return

    onceki_veri = json.loads(ONCEKI.read_text(encoding="utf-8"))
    onceki_evreler = onceki_veri.get("evreler", {})
    onceki_tarih = onceki_veri.get("tarih", "?")

    if LOG.exists():
        log_veri = json.loads(LOG.read_text(encoding="utf-8"))
        gecmis_kayitlar = log_veri.get("kayitlar", [])
    else:
        gecmis_kayitlar = []

    # Sure hesabi icin: bu sektorun en son NE ZAMAN evre degistirdigini bul
    # (log'daki en son kaydindan, yoksa "bilinmiyor")
    son_degisim_tarihi = {}
    for kayit in gecmis_kayitlar:
        son_degisim_tarihi[kayit["kod"]] = kayit["tarih"]

    yeni_degisimler = []
    for kod, sek in guncel_sektorler.items():
        yeni_evre = sek["evre"]
        eski_evre = onceki_evreler.get(kod)
        if eski_evre is None or eski_evre == yeni_evre:
            continue  # yeni sektor ya da degisim yok

        onceki_bu_sektor = son_degisim_tarihi.get(kod, onceki_tarih)
        try:
            gun_farki = (datetime.strptime(bugun, "%Y-%m-%d") - datetime.strptime(onceki_bu_sektor, "%Y-%m-%d")).days
            hafta_farki = max(1, round(gun_farki / 7))
            sure_metni = f"{hafta_farki} hafta"
        except Exception:
            sure_metni = "bilinmiyor"

        yeni_degisimler.append({
            "tarih": bugun,
            "kod": kod,
            "ad": sek["ad"],
            "onceki_evre": eski_evre,
            "yeni_evre": yeni_evre,
            "onceki_evrede_kalma_suresi": sure_metni,
            "not": sablon_cumle(sek["ad"], eski_evre, yeni_evre),
        })

    if yeni_degisimler:
        print(f"{len(yeni_degisimler)} sektorde evre degisikligi tespit edildi:")
        for d in yeni_degisimler:
            print(f"  {d['kod']}: {d['onceki_evre']} -> {d['yeni_evre']}")
    else:
        print("Bu hafta hicbir sektorde evre degisikligi yok.")

    tum_kayitlar = yeni_degisimler + gecmis_kayitlar  # en yeni basta
    tum_kayitlar = tum_kayitlar[:200]  # dosya sismesin, son 200 degisim yeter

    LOG.write_text(json.dumps({
        "guncelleme": datetime.now(timezone.utc).isoformat(),
        "not": "Her hafta otomatik tespit edilen evre gecisleri. 'not' alani sablon cumledir, elle zenginlestirilebilir.",
        "kayitlar": tum_kayitlar,
    }, ensure_ascii=False), encoding="utf-8")

    onceki_kayit = {"tarih": bugun, "evreler": {k: v["evre"] for k, v in guncel_sektorler.items()}}
    ONCEKI.write_text(json.dumps(onceki_kayit, ensure_ascii=False), encoding="utf-8")
    print(f"Tamamlandi -> {LOG} ({len(tum_kayitlar)} toplam kayit)")


if __name__ == "__main__":
    main()
