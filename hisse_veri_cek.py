# -*- coding: utf-8 -*-
"""
GNC Insight - Hisse Fiyat/Piyasa Verisi Cekici (Is Yatirim)
sektor_hisseler.json'daki tum hisseler icin son fiyat, gunluk/haftalik/aylik
getiri, piyasa degeri ve hacmi ceker; gnc-panel/sektor_hisse_veri.json'a yazar.
GitHub Actions ile gunde birkac kez calisir. Panel bu dosyayi okur.
"""

import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from isyatirimhisse import fetch_stock_data

KLASOR = Path(__file__).parent


def kolon_bul(df, adaylar):
    for a in adaylar:
        for c in df.columns:
            if str(c).upper() == a.upper():
                return c
    return None


def yuzde(son, onceki):
    if son is None or onceki in (None, 0) or (isinstance(onceki, float) and math.isnan(onceki)):
        return None
    return round((son / onceki - 1) * 100, 2)


def hisse_kodlari():
    veri = json.loads((KLASOR / "gnc-panel" / "sektor_hisseler.json").read_text(encoding="utf-8"))
    kodlar = []
    for grup in veri["hisseler"].values():
        for h in grup:
            kodlar.append(h["kod"])
    return sorted(set(kodlar))


def main():
    kodlar = hisse_kodlari()
    bugun = datetime.now()
    baslangic = (bugun - timedelta(days=150)).strftime("%d-%m-%Y")
    bitis = bugun.strftime("%d-%m-%Y")

    print(f"{len(kodlar)} hisse cekiliyor (Is Yatirim)...")
    df = fetch_stock_data(symbols=kodlar, start_date=baslangic, end_date=bitis)

    kod_k = kolon_bul(df, ["HGDG_HS_KODU"])
    kap_k = kolon_bul(df, ["HGDG_KAPANIS"])
    tar_k = kolon_bul(df, ["HGDG_TARIH"])
    hac_k = kolon_bul(df, ["HGDG_HACIM", "HG_HACIM", "DOLAR_HACIM"])
    pd_k = kolon_bul(df, ["PD", "PD_TL", "HAO_PD", "HG_PD"])

    sonuc = {}
    for kod in kodlar:
        alt = df[df[kod_k] == kod].sort_values(tar_k) if kod_k else pd.DataFrame()
        if len(alt) < 2:
            sonuc[kod] = {"fiyat": None, "g1": None, "h1": None, "a1": None, "pd": None, "hacim": None}
            print(f"  {kod:6s} veri yok")
            continue
        kapanis = [float(v) for v in alt[kap_k].tolist() if v is not None]
        son = kapanis[-1]
        geri = lambda n: kapanis[-1 - n] if len(kapanis) > n else None
        sonuc[kod] = {
            "fiyat": round(son, 2),
            "g1": yuzde(son, geri(1)),
            "h1": yuzde(son, geri(5)),
            "a1": yuzde(son, geri(21)),
            "pd": float(alt[pd_k].iloc[-1]) if pd_k and not pd.isna(alt[pd_k].iloc[-1]) else None,
            "hacim": float(alt[hac_k].iloc[-1]) if hac_k and not pd.isna(alt[hac_k].iloc[-1]) else None,
        }
        print(f"  {kod:6s} {son}")

    cikti = {"guncelleme": bugun.isoformat(), "kaynak": "Is Yatirim", "hisseler": sonuc}
    hedef = KLASOR / "gnc-panel" / "sektor_hisse_veri.json"
    hedef.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")
    gelen = sum(1 for v in sonuc.values() if v["fiyat"] is not None)
    print(f"\nTamamlandi: {gelen}/{len(kodlar)} hisse -> {hedef}")


if __name__ == "__main__":
    main()
