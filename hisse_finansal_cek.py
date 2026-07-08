# -*- coding: utf-8 -*-
"""
GNC Insight - Hisse Finansal (Bilanco/Gelir Tablosu) Cekici
sektor_hisseler.json'daki her hisse icin Is Yatirim'dan finansal tablolari ceker
ve gnc-panel/finansal/{KOD}.json dosyasina yazar. Hisseye tiklayinca panel bu
dosyayi okur. Finansallar ceyrekte bir degistigi icin ayda bir calisir.
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from isyatirimhisse import fetch_financials

KLASOR = Path(__file__).parent
BASE_COLS = {"SYMBOL", "FINANCIAL_ITEM_CODE", "FINANCIAL_ITEM_NAME_TR", "FINANCIAL_ITEM_NAME_EN"}
DONEM_SAYISI = 8  # son 8 donem


def hisse_kodlari():
    veri = json.loads((KLASOR / "gnc-panel" / "sektor_hisseler.json").read_text(encoding="utf-8"))
    kodlar = []
    for grup in veri["hisseler"].values():
        for h in grup:
            kodlar.append(h["kod"])
    return sorted(set(kodlar))


def temizle_deger(x):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    try:
        return round(float(x), 0)
    except Exception:
        return None


def hisse_finansal(kod, yil_bas, yil_bit):
    """Bir hisse icin finansal tablo -> {donemler:[...], kalemler:[{ad, degerler:{}}]}."""
    df = None
    for grup in ("1", "2"):  # 1: sinai/hizmet, 2: banka/finans
        try:
            d = fetch_financials(symbols=[kod], start_year=yil_bas, end_year=yil_bit, financial_group=grup)
            if d is not None and len(d) > 5:
                df = d
                break
        except Exception:
            continue
    if df is None or not len(df):
        return None

    donem_kol = [c for c in df.columns if c not in BASE_COLS]
    # donemleri tarihe gore sirala (en yeni once), son N tanesi
    def anahtar(c):
        try:
            y, q = str(c).split("/"); return (int(y), int(q))
        except Exception:
            return (0, 0)
    donem_kol = sorted(donem_kol, key=anahtar, reverse=True)[:DONEM_SAYISI]

    kalemler = []
    for _, r in df.iterrows():
        ad = r.get("FINANCIAL_ITEM_NAME_TR")
        if not ad:
            continue
        degerler = {}
        for d in donem_kol:
            v = temizle_deger(r.get(d))
            if v is not None:
                degerler[d] = v
        if degerler:
            kalemler.append({"ad": str(ad).strip(), "degerler": degerler})

    if not kalemler:
        return None
    return {"donemler": donem_kol, "kalemler": kalemler}


def main():
    kodlar = hisse_kodlari()
    yil = datetime.now().year
    hedef_klasor = KLASOR / "gnc-panel" / "finansal"
    hedef_klasor.mkdir(parents=True, exist_ok=True)

    ok = 0
    for kod in kodlar:
        try:
            fin = hisse_finansal(kod, yil - 3, yil)
            if fin:
                fin["kod"] = kod
                fin["guncelleme"] = datetime.now().isoformat()
                (hedef_klasor / f"{kod}.json").write_text(json.dumps(fin, ensure_ascii=False), encoding="utf-8")
                ok += 1
                print(f"  {kod:6s} {len(fin['kalemler'])} kalem")
            else:
                print(f"  {kod:6s} finansal yok")
        except Exception as e:
            print(f"  {kod:6s} hata: {e}")

    print(f"\nTamamlandi: {ok}/{len(kodlar)} hisse -> {hedef_klasor}")


if __name__ == "__main__":
    main()
