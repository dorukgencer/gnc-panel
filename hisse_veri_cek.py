# -*- coding: utf-8 -*-
"""
GNC Insight - Hisse Fiyat/Piyasa Verisi Cekici (Is Yatirim) - DAYANIKLI
sektor_hisseler.json'daki tum hisseler icin son fiyat, gunluk/haftalik/aylik
getiri, piyasa degeri ve hacmi ceker; gnc-panel/sektor_hisse_veri.json'a yazar.

DAYANIKLILIK (sektor_cek.py ile ayni mantik):
- Hisseler GRUPLAR halinde (retry ile) cekilir; bir grup timeout olsa digerleri devam eder.
- Taze gelmeyen hisse icin ELDEKI ESKI deger korunur (bosluk olusmaz).
- Hic taze veri gelmezse mevcut dosyaya DOKUNULMAZ (panel eski saglam veriyle calisir).
- guncelleme UTC-farkli yazilir (sektor ile ayni format -> panelde saat kaymasi olmaz).
"""

import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from isyatirimhisse import fetch_stock_data

KLASOR = Path(__file__).parent
GRUP_BOYUT = 50     # tek istekte kac hisse
DENEME = 3          # her grup icin tekrar sayisi
BEKLE = 2           # denemeler arasi saniye


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


def eski_yukle(hedef):
    if hedef.exists():
        try:
            data = json.loads(hedef.read_text(encoding="utf-8"))
            return data.get("hisseler", {}) or {}
        except Exception as e:
            print(f"Eski dosya okunamadi: {e}")
    return {}


def grup_cek(kodlar, baslangic, bitis):
    """Bir grup hisseyi retry ile ceker; basarisizsa None."""
    for i in range(DENEME):
        try:
            df = fetch_stock_data(symbols=kodlar, start_date=baslangic, end_date=bitis)
            if df is not None and len(df):
                return df
        except Exception as e:
            print(f"  grup [{kodlar[0]}..{kodlar[-1]}] deneme {i+1}/{DENEME} hata: {str(e)[:60]}")
        if i < DENEME - 1:
            time.sleep(BEKLE)
    return None


def hisse_isle(df, kod, kod_k, kap_k, tar_k, hac_k, pd_k):
    if not kod_k:
        return None
    alt = df[df[kod_k] == kod].sort_values(tar_k)
    if len(alt) < 2:
        return None
    kapanis = [float(v) for v in alt[kap_k].tolist() if v is not None]
    if len(kapanis) < 2:
        return None
    son = kapanis[-1]
    geri = lambda n: kapanis[-1 - n] if len(kapanis) > n else None
    return {
        "fiyat": round(son, 2),
        "g1": yuzde(son, geri(1)),
        "h1": yuzde(son, geri(5)),
        "a1": yuzde(son, geri(21)),
        "pd": float(alt[pd_k].iloc[-1]) if pd_k and not pd.isna(alt[pd_k].iloc[-1]) else None,
        "hacim": float(alt[hac_k].iloc[-1]) if hac_k and not pd.isna(alt[hac_k].iloc[-1]) else None,
    }


def main():
    kodlar = hisse_kodlari()
    bugun = datetime.now()
    baslangic = (bugun - timedelta(days=150)).strftime("%d-%m-%Y")
    bitis = bugun.strftime("%d-%m-%Y")

    hedef = KLASOR / "gnc-panel" / "sektor_hisse_veri.json"
    hedef.parent.mkdir(parents=True, exist_ok=True)
    eski = eski_yukle(hedef)

    print(f"{len(kodlar)} hisse {GRUP_BOYUT}'li gruplarla cekiliyor (Is Yatirim)...")
    sonuc = {}
    taze_sayi = 0

    for i in range(0, len(kodlar), GRUP_BOYUT):
        parca = kodlar[i:i + GRUP_BOYUT]
        df = grup_cek(parca, baslangic, bitis)
        if df is None:
            print(f"  grup {i}-{i+len(parca)}: taze gelmedi (eski korunacak)")
            continue
        kod_k = kolon_bul(df, ["HGDG_HS_KODU"])
        kap_k = kolon_bul(df, ["HGDG_KAPANIS"])
        tar_k = kolon_bul(df, ["HGDG_TARIH"])
        hac_k = kolon_bul(df, ["HGDG_HACIM", "HG_HACIM", "DOLAR_HACIM"])
        pd_k = kolon_bul(df, ["PD", "PD_TL", "HAO_PD", "HG_PD"])
        for kod in parca:
            v = hisse_isle(df, kod, kod_k, kap_k, tar_k, hac_k, pd_k)
            if v is not None:
                sonuc[kod] = v
                taze_sayi += 1
        print(f"  grup {i}-{i+len(parca)}: tamam")

    # Taze gelmeyen hisseler icin eski degeri koru
    korunan = 0
    for kod in kodlar:
        if kod not in sonuc:
            if kod in eski and eski[kod].get("fiyat") is not None:
                sonuc[kod] = eski[kod]
                korunan += 1
            else:
                sonuc[kod] = {"fiyat": None, "g1": None, "h1": None, "a1": None, "pd": None, "hacim": None}

    # Hic taze veri gelmediyse mevcut dosyaya dokunma
    if taze_sayi == 0:
        print("\nHic taze veri gelmedi. Mevcut dosya KORUNUYOR (yazilmadi).")
        return

    cikti = {
        "guncelleme": datetime.now(timezone.utc).isoformat(),
        "kaynak": "Is Yatirim",
        "hisseler": sonuc,
    }
    hedef.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")
    print(f"\nTamamlandi: {taze_sayi} taze + {korunan} korunan / {len(kodlar)} hisse -> {hedef}")


if __name__ == "__main__":
    main()
