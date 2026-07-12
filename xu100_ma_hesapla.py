# -*- coding: utf-8 -*-
"""
GNC Insight - XU100 200 Gunluk Ortalama Mesafesi
gnc-panel/endeks_gecmis/XU100.json (zaten cekilmis gunluk veri) uzerinden
200 gunluk hareketli ortalamayi ve XU100'un buna yuzde mesafesini hesaplar.
YENI VERI CEKMEZ - saf hesaplama.

Cikti: gnc-panel/xu100_ma_mesafe.json
"""

import json
from datetime import datetime, timezone
from pathlib import Path

KLASOR = Path(__file__).parent
KAYNAK = KLASOR / "gnc-panel" / "endeks_gecmis" / "XU100.json"
HEDEF = KLASOR / "gnc-panel" / "xu100_ma_mesafe.json"

PENCERE = 200


def main():
    if not KAYNAK.exists():
        raise SystemExit(f"{KAYNAK} bulunamadi. Once endeks_gecmis_cek.py calismis olmali.")

    veri = json.loads(KAYNAK.read_text(encoding="utf-8"))
    seri = sorted(veri.get("seri", []), key=lambda s: s["tarih"])

    if len(seri) < PENCERE:
        raise SystemExit(f"Yetersiz veri: {len(seri)} gun var, {PENCERE} gun gerekiyor.")

    kapanislar = [s["kapanis"] for s in seri]
    son_kapanis = kapanislar[-1]
    ma200 = sum(kapanislar[-PENCERE:]) / PENCERE
    mesafe_yuzde = (son_kapanis / ma200 - 1) * 100

    cikti = {
        "guncelleme": datetime.now(timezone.utc).isoformat(),
        "not": f"XU100'un son kapanisinin {PENCERE} gunluk ortalamaya gore yuzde mesafesi. Pozitif = ortalamanin uzerinde (gerilmis), negatif = altinda.",
        "son_kapanis": round(son_kapanis, 2),
        "ma200": round(ma200, 2),
        "mesafe_yuzde": round(mesafe_yuzde, 2),
        "veri_son_tarih": seri[-1]["tarih"],
    }
    HEDEF.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")
    print(f"XU100 son kapanis: {son_kapanis}, MA200: {round(ma200,2)}, mesafe: %{round(mesafe_yuzde,2)}")
    print(f"Tamamlandi -> {HEDEF}")


if __name__ == "__main__":
    main()
