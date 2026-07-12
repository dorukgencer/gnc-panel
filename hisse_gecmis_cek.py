# -*- coding: utf-8 -*-
"""
GNC Insight - Hisse Gunluk Fiyat Gecmisi Cekici - TOPLU
sektor_hisse_veri.json SADECE son fiyat + kisa donem getiriyi tutar (g1/h1/a1).
Bu script ise her hisse icin GUNLUK KAPANIS SERISINI (varsayilan ~2 yil) ceker
ve gnc-panel/hisse_gecmis/{KOD}.json olarak yazar.

Amac: reel getiri (1Y/YBB icin uzun seri gerekir) ve ileride teknik analiz
modulu (destek/direnc) icin ham fiyat serisi. Finansal tablolar gibi
per-hisse dosya olarak tutulur -> panel sadece kullanicinin actigi hissenin
dosyasini ceker, tum seriyi her sayfa yuklemesinde tasimaz.

Sik calismaz (gunde 1 kez yeter, fiyat serisi gun icinde onemli degismez).
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from isyatirimhisse import fetch_stock_data

KLASOR = Path(__file__).parent
GRUP_BOYUT = 50
DENEME = 3
BEKLE = 2
GUN_SAYISI = 3700  # ~10 yil (hafta sonu/tatil dahil takvim gunu)
PARALEL_ISCI = 4  # ayni anda kac grup istegi atilsin


def hisse_kodlari():
    veri = json.loads((KLASOR / "gnc-panel" / "sektor_hisseler.json").read_text(encoding="utf-8"))
    kodlar = []
    for grup in veri["hisseler"].values():
        for h in grup:
            kodlar.append(h["kod"])
    return sorted(set(kodlar))


def kolon_bul(df, adaylar):
    for a in adaylar:
        for c in df.columns:
            if str(c).upper() == a.upper():
                return c
    return None


def grup_cek(kodlar, baslangic, bitis):
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


def main():
    kodlar = hisse_kodlari()
    bugun = datetime.now()
    baslangic = (bugun - timedelta(days=GUN_SAYISI)).strftime("%d-%m-%Y")
    bitis = bugun.strftime("%d-%m-%Y")

    hedef_klasor = KLASOR / "gnc-panel" / "hisse_gecmis"
    hedef_klasor.mkdir(parents=True, exist_ok=True)

    print(f"{len(kodlar)} hisse icin ~{GUN_SAYISI} gunluk gecmis {GRUP_BOYUT}'li gruplarla, {PARALEL_ISCI} paralel istekle cekiliyor...")
    now_iso = datetime.now(timezone.utc).isoformat()
    ok = 0

    gruplar = [kodlar[i:i + GRUP_BOYUT] for i in range(0, len(kodlar), GRUP_BOYUT)]

    def grup_isle(parca):
        df = grup_cek(parca, baslangic, bitis)
        if df is None:
            return parca, None
        kod_k = kolon_bul(df, ["HGDG_HS_KODU"])
        kap_k = kolon_bul(df, ["HGDG_KAPANIS"])
        tar_k = kolon_bul(df, ["HGDG_TARIH"])
        if not kod_k or not kap_k or not tar_k:
            return parca, None
        yazilan = []
        for kod in parca:
            alt = df[df[kod_k] == kod].sort_values(tar_k)
            if len(alt) < 2:
                continue
            seri = []
            for _, r in alt.iterrows():
                v = r.get(kap_k)
                t = r.get(tar_k)
                if v is None or pd.isna(v) or t is None:
                    continue
                try:
                    tarih_str = pd.to_datetime(t).strftime("%Y-%m-%d")
                except Exception:
                    continue
                seri.append({"tarih": tarih_str, "kapanis": round(float(v), 2)})
            if len(seri) < 2:
                continue
            cikti = {"kod": kod, "guncelleme": now_iso, "gun_sayisi": len(seri), "seri": seri}
            (hedef_klasor / f"{kod}.json").write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")
            yazilan.append(kod)
        return parca, yazilan

    with ThreadPoolExecutor(max_workers=PARALEL_ISCI) as havuz:
        gelecekler = {havuz.submit(grup_isle, parca): parca for parca in gruplar}
        for gelecek in as_completed(gelecekler):
            parca = gelecekler[gelecek]
            ilk, son = parca[0], parca[-1]
            try:
                _, yazilan = gelecek.result()
            except Exception as e:
                print(f"  grup [{ilk}..{son}]: hata {str(e)[:60]}")
                continue
            if yazilan is None:
                print(f"  grup [{ilk}..{son}]: cekilemedi, atlaniyor (eski dosyalar korunur)")
                continue
            ok += len(yazilan)
            print(f"  grup [{ilk}..{son}]: tamam ({len(yazilan)} hisse)")

    print(f"\nTamamlandi: {ok}/{len(kodlar)} hisse -> {hedef_klasor}")


if __name__ == "__main__":
    main()
