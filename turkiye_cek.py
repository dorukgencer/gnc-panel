# -*- coding: utf-8 -*-
"""
GNC Insight - Turkiye Makro Verisi (TCMB EVDS / borsapy)
TUFE (yillik+aylik), UFE, politika faizi ve USD/TRY verilerini ceker;
her biri icin son + onceki + gecmis + yorum uretip gnc-panel/turkiye_veri.json'a
yazar. EVDS anahtari GitHub secret'tan (EVDS_API_KEY) gelir.
GitHub Actions ile gunde birkac kez calisir.
"""

import json
import os
from datetime import datetime
from pathlib import Path

import borsapy as bp

# EVDS anahtari (secret'tan). Bazi yardimcilar icin gerekli.
key = os.environ.get("EVDS_API_KEY")
if key:
    try:
        bp.set_evds_key(key)
    except Exception as e:
        print("set_evds_key uyari:", e)

YORUM = {
    "tufe_y": "Yıllık tüketici enflasyonu (TÜFE). Yükselmesi fiyat baskısının arttığını, düşmesi enflasyonda gevşemeyi gösterir. TCMB faiz kararlarının ana çıpasıdır.",
    "tufe_a": "Aylık tüketici enflasyonu; enflasyonun kısa vadeli hızını gösterir. Yüksek aylık okumalar yıllık enflasyonun yapışkan kaldığına işaret eder.",
    "ufe_y": "Yıllık üretici (yurt içi) enflasyonu (Yİ-ÜFE); maliyet baskısının öncü göstergesi. ÜFE'deki artış zamanla tüketici fiyatlarına (TÜFE) yansıyabilir.",
    "faiz": "TCMB'nin belirlediği politika faizi. Yükselmesi parasal sıkılaşma, düşmesi gevşeme demektir; kur, tahvil ve hisse için ana yön belirleyicidir.",
    "usdtry": "Doların TL karşısındaki değeri. Yükselmesi TL'nin değer kaybettiğini gösterir; enflasyon, ithalat maliyeti ve dış borç açısından kritiktir.",
}


def seri_kaydi(isim, birim, deger_listesi, yorum):
    """deger_listesi: kronolojik (eski->yeni) sayilar."""
    d = [float(x) for x in deger_listesi if x is not None]
    if len(d) < 1:
        return None
    return {
        "isim": isim, "birim": birim,
        "son": round(d[-1], 2),
        "onceki": round(d[-2], 2) if len(d) > 1 else None,
        "gecmis": [round(x, 2) for x in d[-12:]],
        "yorum": yorum,
    }


def main():
    veriler = []
    inf = bp.Inflation()

    # TUFE (yillik + aylik)
    try:
        t = inf.tufe(limit=18).sort_index()
        y = seri_kaydi("TÜFE (Yıllık)", "yuzde", t["YearlyInflation"].tolist(), YORUM["tufe_y"])
        a = seri_kaydi("TÜFE (Aylık)", "yuzde", t["MonthlyInflation"].tolist(), YORUM["tufe_a"])
        if y: veriler.append(y)
        if a: veriler.append(a)
        print("TUFE tamam")
    except Exception as e:
        print("TUFE hata:", e)

    # UFE (yillik)
    try:
        u = inf.ufe(limit=18).sort_index()
        uy = seri_kaydi("ÜFE (Yıllık)", "yuzde", u["YearlyInflation"].tolist(), YORUM["ufe_y"])
        if uy: veriler.append(uy)
        print("UFE tamam")
    except Exception as e:
        print("UFE hata:", e)

    # Politika faizi
    try:
        tc = bp.TCMB()
        pr = tc.policy_rate
        if hasattr(pr, "iloc"):
            seri = pr.iloc[:, -1].tolist() if hasattr(pr, "columns") else pr.tolist()
            f = seri_kaydi("Politika Faizi", "yuzde", seri, YORUM["faiz"])
        else:
            f = {"isim": "Politika Faizi", "birim": "yuzde", "son": round(float(pr), 2), "onceki": None, "gecmis": [], "yorum": YORUM["faiz"]}
        if f: veriler.append(f)
        print("Faiz tamam")
    except Exception as e:
        print("Faiz hata:", e)

    # USD/TRY
    try:
        fx = bp.FX("USD")
        h = fx.history(period="6mo")
        kol = "Close" if "Close" in h.columns else h.columns[-1]
        d = seri_kaydi("USD/TRY", "kur", h[kol].tolist(), YORUM["usdtry"])
        if d: veriler.append(d)
        print("USDTRY tamam")
    except Exception as e:
        print("USDTRY hata:", e)

    cikti = {"guncelleme": datetime.now().isoformat(), "kaynak": "TCMB EVDS / borsapy", "veriler": veriler}
    hedef = Path(__file__).parent / "gnc-panel" / "turkiye_veri.json"
    hedef.parent.mkdir(parents=True, exist_ok=True)
    hedef.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")
    print(f"\nTamamlandi: {len(veriler)} veri -> {hedef}")


if __name__ == "__main__":
    main()
