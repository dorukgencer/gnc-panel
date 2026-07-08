# -*- coding: utf-8 -*-
"""
GNC Insight - Turkiye Ekonomik Takvim Cekici (tarihli)
borsapy EconomicCalendar (kaynak: doviz.com) uzerinden Turkiye makro takvimini
ceker: tarih + saat + olay + onem + aciklanan + onceki + beklenti.
gnc-panel/turkiye_takvim.json'a yazar. API anahtari gerektirmez.
"""

import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import borsapy as bp


def temiz(x):
    if x is None:
        return None
    if isinstance(x, float) and math.isnan(x):
        return None
    s = str(x).strip()
    return s if s and s.lower() != "nan" else None


def main():
    bugun = datetime.now()
    bas = (bugun - timedelta(days=30)).strftime("%Y-%m-%d")
    bit = (bugun + timedelta(days=40)).strftime("%Y-%m-%d")

    print("Turkiye takvimi cekiliyor (doviz.com)...")
    cal = bp.EconomicCalendar()
    df = cal.events(start=bas, end=bit, country="TR")

    olaylar = []
    if df is not None and len(df):
        for _, r in df.iterrows():
            olaylar.append({
                "tarih": temiz(r.get("Date")),
                "saat": temiz(r.get("Time")),
                "olay": temiz(r.get("Event")),
                "onem": temiz(r.get("Importance")),
                "aciklanan": temiz(r.get("Actual")),
                "beklenti": temiz(r.get("Forecast")),
                "onceki": temiz(r.get("Previous")),
                "donem": temiz(r.get("Period")),
            })

    cikti = {"guncelleme": bugun.isoformat(), "kaynak": "doviz.com", "olaylar": olaylar}
    hedef = Path(__file__).parent / "gnc-panel" / "turkiye_takvim.json"
    hedef.parent.mkdir(parents=True, exist_ok=True)
    hedef.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")
    print(f"Tamamlandi: {len(olaylar)} olay -> {hedef}")


if __name__ == "__main__":
    main()
