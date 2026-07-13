# -*- coding: utf-8 -*-
"""
GNC Insight - Gunluk Arsiv (Endekse Katki + Degerleme)
Her gun BORSA KAPANISINDAN SONRA (piyasa_cek.py'nin son calismasindan ve
deger_hesapla.py'den SONRA) calisir. O GUNUN SONUNDAKI (18:00 TR kapanisi)
Endekse Katki ve Degerleme durumunu, BUGUNUN TARIHI ile bir arsive EKLER
(uzerine yazmaz - her gun yeni bir kayit birikir).

Boylece kullanici "3 gun once hangi sektor endekse ne kadar katki yapmisti,
F/K nasildi" diye SORABILIR - bu bilgi anlik veriden kaybolmadan once
"donduruluyor".

Cikti: gnc-panel/gunluk_arsiv.json
Format: {"gunler": {"2026-07-13": {"katki": {kod: {ad,g1,h1,a1,agirlik}}, 
                                     "deger": {kod: {fk_guncel_medyan,sapma_yuzde,pd_dd_medyan}}}}}

SAKLAMA SURESI: son 60 gun (5 gunluk buton icin fazlasiyla yeterli, "biriksin"
felsefesiyle biraz cömert tutuldu ama sinirsiz degil - gunluk cozunurlukte
sinirsiz birikim yillar icinde gereksiz buyur).
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

KLASOR = Path(__file__).parent
ARSIV = KLASOR / "gnc-panel" / "gunluk_arsiv.json"
SAKLAMA_GUN = 60


def main():
    bugun = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # --- Endekse Katki icin gereken ham veri: sektor_verisi.json (getiri) + rotasyon_gecmis.json (GERCEK agirlik) ---
    try:
        sektor_verisi = json.loads((KLASOR / "gnc-panel" / "sektor_verisi.json").read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"sektor_verisi.json okunamadi: {e}")
    try:
        rotasyon = json.loads((KLASOR / "gnc-panel" / "rotasyon_gecmis.json").read_text(encoding="utf-8"))
        agirlik_harita = {s["kod"]: s.get("agirlik") for s in rotasyon.get("sektorler", [])}
    except Exception:
        agirlik_harita = {}

    # DUZELTME (13 Tem 2026): katki artik rotasyon_turetilmis.json'dan (SUNUCUDA
    # hesaplanmis HAZIR deger) okunuyor - boylece arsiv ile canli gorunum AYNI
    # hesabi kullanir, tutarsizlik olmaz. O dosya yoksa ham veriden turetilir.
    turetilmis = None
    try:
        turetilmis = json.loads((KLASOR / "gnc-panel" / "rotasyon_turetilmis.json").read_text(encoding="utf-8"))
    except Exception:
        pass

    katki_gunu = {}
    if turetilmis and turetilmis.get("endekse_katki"):
        katki_gunu = dict(turetilmis["endekse_katki"])
        print(f"  katki: rotasyon_turetilmis.json'dan {len(katki_gunu)} sektor (hazir degerler)")
    else:
        for e in sektor_verisi.get("endeksler", []):
            if e.get("tip") != "sektor":
                continue
            agirlik = agirlik_harita.get(e["kod"])
            girdi = {"ad": e.get("ad"), "agirlik": agirlik}
            if agirlik is not None:
                for p_ in ("g1", "h1", "a1"):
                    g = e.get(p_)
                    if g is not None:
                        girdi[f"katki_{p_}"] = round((agirlik / 100.0) * g, 4)
            katki_gunu[e["kod"]] = girdi
        print(f"  katki: rotasyon_turetilmis.json yok, ham veriden turetildi ({len(katki_gunu)} sektor)")

    # --- Degerleme icin: degerleme_gecmis.json'u OLDUGU GIBI kopyala ---
    deger_gunu = {}
    try:
        deger = json.loads((KLASOR / "gnc-panel" / "degerleme_gecmis.json").read_text(encoding="utf-8"))
        for kod, v in deger.get("sektorler", {}).items():
            deger_gunu[kod] = {
                "fk_guncel_medyan": v.get("fk_guncel_medyan"),
                "sapma_yuzde": v.get("sapma_yuzde"),
                "pd_dd_medyan": v.get("pd_dd_medyan"),
                "guven_dusuk": v.get("guven_dusuk"),
            }
    except Exception as e:
        print(f"  degerleme_gecmis.json okunamadi (bu gun icin deger arsivlenemeyecek): {e}")

    if not katki_gunu and not deger_gunu:
        raise SystemExit("Ne katki ne deger verisi bulunamadi - hicbir sey arsivlenmedi.")

    # --- Mevcut arsivi yukle, bugunku kaydi EKLE (uzerine yazma, birikir) ---
    if ARSIV.exists():
        try:
            arsiv_veri = json.loads(ARSIV.read_text(encoding="utf-8"))
        except Exception:
            arsiv_veri = {"gunler": {}}
    else:
        arsiv_veri = {"gunler": {}}

    arsiv_veri["gunler"][bugun] = {"katki": katki_gunu, "deger": deger_gunu}

    # --- Eski kayitlari temizle (SAKLAMA_GUN'den eski) ---
    sinir_tarih = (datetime.now(timezone.utc) - timedelta(days=SAKLAMA_GUN)).strftime("%Y-%m-%d")
    eski_gun_sayisi = len(arsiv_veri["gunler"])
    arsiv_veri["gunler"] = {g: v for g, v in arsiv_veri["gunler"].items() if g >= sinir_tarih}
    silinen = eski_gun_sayisi - len(arsiv_veri["gunler"])

    arsiv_veri["guncelleme"] = datetime.now(timezone.utc).isoformat()
    arsiv_veri["not"] = (
        f"Her gun borsa kapanisindan sonra o gunun Endekse Katki ve Degerleme "
        f"durumunu dondurur. Son {SAKLAMA_GUN} gun saklanir, daha eskisi silinir."
    )

    ARSIV.write_text(json.dumps(arsiv_veri, ensure_ascii=False), encoding="utf-8")
    print(f"Bugun ({bugun}) arsive eklendi: {len(katki_gunu)} sektor katki, {len(deger_gunu)} sektor deger")
    print(f"Toplam arsivlenmis gun sayisi: {len(arsiv_veri['gunler'])}" + (f" ({silinen} eski gun silindi)" if silinen else ""))
    print(f"Tamamlandi -> {ARSIV}")


if __name__ == "__main__":
    main()
