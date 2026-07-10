# -*- coding: utf-8 -*-
"""
GNC Insight - Hisse Finansal (Bilanco/Gelir Tablosu) Cekici - TOPLU
sektor_hisseler.json'daki hisseleri GRUPLAR halinde (tek istekte coklu sembol)
Is Yatirim'dan ceker; her hisse icin gnc-panel/finansal/{KOD}.json yazar.
Tek tek cekmek yerine toplu cektigi icin cok daha hizli.
"""

import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
from isyatirimhisse import fetch_financials

KLASOR = Path(__file__).parent
BASE_COLS = {"SYMBOL", "FINANCIAL_ITEM_CODE", "FINANCIAL_ITEM_NAME_TR", "FINANCIAL_ITEM_NAME_EN"}
DONEM_SAYISI = 40  # ~10 yil (ceyreklik) - eskiden 24 (~6 yil)
GRUP_BOYUT = 25   # tek istekte kac sembol


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


def parcala(df):
    """Coklu-sembol DataFrame -> {KOD: {donemler, kalemler}}."""
    sonuc = {}
    if df is None or not len(df) or "SYMBOL" not in df.columns:
        return sonuc
    # Donem kolonlari: sadece "YYYY/M" desenine uyanlar (fazladan kolonlari elemek icin)
    donem_kol = [c for c in df.columns if c not in BASE_COLS and re.match(r"^\d{4}/\d{1,2}$", str(c))]

    def anahtar(c):
        try:
            y, q = str(c).split("/"); return (int(y), int(q))
        except Exception:
            return (0, 0)
    donem_kol = sorted(donem_kol, key=anahtar, reverse=True)[:DONEM_SAYISI]

    for kod, grp in df.groupby("SYMBOL"):
        kalemler = []
        for _, r in grp.iterrows():
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
        if kalemler:
            sonuc[str(kod).strip()] = {"donemler": donem_kol, "kalemler": kalemler}
    return sonuc


def toplu_cek(kodlar, yil_bas, yil_bit, grup):
    """kodlar listesini GRUP_BOYUT'luk parcalarla toplu ceker."""
    bulunan = {}
    for i in range(0, len(kodlar), GRUP_BOYUT):
        parca = kodlar[i:i + GRUP_BOYUT]
        try:
            df = fetch_financials(symbols=parca, start_year=yil_bas, end_year=yil_bit, financial_group=grup)
            cikan = parcala(df)
            bulunan.update(cikan)
            print(f"  grup {grup} [{i}-{i+len(parca)}]: {len(cikan)} hisse")
        except Exception as e:
            print(f"  grup {grup} [{i}-{i+len(parca)}] hata: {e}")
    return bulunan


def main():
    kodlar = hisse_kodlari()
    yil = datetime.now().year
    hedef_klasor = KLASOR / "gnc-panel" / "finansal"
    hedef_klasor.mkdir(parents=True, exist_ok=True)

    # Grup onceligi: 3 = UFRS Konsolide, 2 = UFRS (solo), 1 = eski XI_29.
    # Yeterli dolulukta (>=10 kalem) gelen ilk grup kullanilir; bankalar da
    # dogru guncel formatta (Kar Payi Geliri vb.) UFRS'ten gelir.
    MIN_KALEM = 10
    veriler = {}
    for grup in ("3", "2", "1"):
        kalan = [k for k in kodlar if k not in veriler]
        if not kalan:
            break
        print(f"Grup {grup} icin {len(kalan)} hisse deneniyor...")
        yeni = toplu_cek(kalan, yil - 10, yil, grup)
        for kod, fin in yeni.items():
            if len(fin.get("kalemler", [])) >= MIN_KALEM:
                veriler[kod] = fin

    # Hala bos kalan varsa esigi dusurup ne bulduysak al (eski/kismi tablolar)
    kalan = [k for k in kodlar if k not in veriler]
    if kalan:
        for grup in ("3", "2", "1"):
            kalan = [k for k in kodlar if k not in veriler]
            if not kalan:
                break
            yeni = toplu_cek(kalan, yil - 10, yil, grup)
            veriler.update(yeni)

    # Yaz
    ok = 0
    now = datetime.now().isoformat()
    for kod, fin in veriler.items():
        fin["kod"] = kod
        fin["guncelleme"] = now
        (hedef_klasor / f"{kod}.json").write_text(json.dumps(fin, ensure_ascii=False), encoding="utf-8")
        ok += 1

    print(f"\nTamamlandi: {ok}/{len(kodlar)} hisse -> {hedef_klasor}")


if __name__ == "__main__":
    main()
