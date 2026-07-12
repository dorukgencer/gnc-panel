# -*- coding: utf-8 -*-
"""
GNC Insight - Endeks Gunluk Fiyat Gecmisi Cekici (XU100 + sektorler)
sektor_gecmis.json SADECE aylik getiri tutar (10 yil, ama gunluk cozunurluk
yok). Bu script ise XU100 ve tum sektor endekslerinin GUNLUK kapanis
serisini (~10 yil) ceker; gnc-panel/endeks_gecmis/{KOD}.json olarak yazar.

Amac: 200 gunluk ortalama mesafesi, uzun donem modelleme, gelecekteki
teknik analiz modulu icin XU100'un kendisinin (sadece sektorlerin degil)
gunluk fiyat gecmisi. hisse_gecmis_cek.py ile ayni per-varlik dosya deseni.

Sik calismaz (gunde 1 kez yeter).
"""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from isyatirimhisse import fetch_index_data

KLASOR = Path(__file__).parent
GUN_SAYISI = 3700  # ~10 yil
PARALEL_ISCI = 4

ENDEKSLER = [
    ("XU100", "BIST 100"),
    ("XBANK", "Bankacilik"), ("XSGRT", "Sigorta"), ("XFINK", "Fin. Kiralama Faktoring"),
    ("XHOLD", "Holding ve Yatirim"), ("XGYO", "Gayrimenkul Yat. Ort."),
    ("XYORT", "Menkul Kiymet Yat. Ort."), ("XGIDA", "Gida ve Icecek"),
    ("XKMYA", "Kimya Petrol Plastik"), ("XMANA", "Metal Ana Sanayi"),
    ("XMESY", "Metal Esya Makina"), ("XTAST", "Tas Toprak (Cam Cimento)"),
    ("XTEKS", "Tekstil ve Deri"), ("XKAGT", "Orman Kagit Basim"),
    ("XELKT", "Elektrik"), ("XILTM", "Iletisim"), ("XULAS", "Ulastirma"),
    ("XTCRT", "Ticaret"), ("XTRZM", "Turizm"), ("XINSA", "Insaat ve Bayindirlik"),
    ("XMADN", "Madencilik"), ("XBLSM", "Bilisim"), ("XSPOR", "Spor"),
    ("XUTEK", "Teknoloji"),
]

DENEME = 3
BEKLE = 2


def cek_tek(kod, baslangic, bitis):
    for i in range(DENEME):
        try:
            df = fetch_index_data(indices=[kod], start_date=baslangic, end_date=bitis)
            if df is not None and len(df):
                return df
        except Exception as e:
            print(f"  {kod:6s} deneme {i+1}/{DENEME} hata: {str(e)[:70]}")
        if i < DENEME - 1:
            import time
            time.sleep(BEKLE)
    return None


def main():
    bugun = datetime.now()
    baslangic = (bugun - timedelta(days=GUN_SAYISI)).strftime("%d-%m-%Y")
    bitis = bugun.strftime("%d-%m-%Y")

    hedef_klasor = KLASOR / "gnc-panel" / "endeks_gecmis"
    hedef_klasor.mkdir(parents=True, exist_ok=True)

    kodlar = [k for k, _ in ENDEKSLER]
    print(f"{len(kodlar)} endeks icin ~{GUN_SAYISI} gunluk gecmis cekiliyor...")
    now_iso = datetime.now(timezone.utc).isoformat()
    ok = 0

    try:
        df_toplu = fetch_index_data(indices=kodlar, start_date=baslangic, end_date=bitis)
    except Exception as e:
        print(f"  toplu cekim hata: {str(e)[:100]}")
        df_toplu = None

    eksikler = []
    hazir = {}
    for kod, ad in ENDEKSLER:
        if df_toplu is not None and "INDEX" in df_toplu.columns:
            alt = df_toplu[df_toplu["INDEX"] == kod].sort_values("DATE")
            if len(alt) >= 30:
                hazir[kod] = alt
                continue
        eksikler.append((kod, ad))

    # Toplu cekimde eksik kalanlari PARALEL tek tek dene (once sirali idi)
    if eksikler:
        print(f"  {len(eksikler)} endeks toplu cekimde eksikti, paralel tek tek deneniyor...")
        with ThreadPoolExecutor(max_workers=PARALEL_ISCI) as havuz:
            gelecekler = {havuz.submit(cek_tek, kod, baslangic, bitis): kod for kod, _ in eksikler}
            for gelecek in as_completed(gelecekler):
                kod = gelecekler[gelecek]
                try:
                    tek = gelecek.result()
                except Exception as e:
                    print(f"  {kod:6s} hata: {str(e)[:60]}")
                    continue
                if tek is not None:
                    alt = tek[tek["INDEX"] == kod].sort_values("DATE") if "INDEX" in tek.columns else tek.sort_values("DATE")
                    if len(alt) >= 30:
                        hazir[kod] = alt

    for kod, ad in ENDEKSLER:
        df = hazir.get(kod)
        if df is None or len(df) < 30:
            print(f"  {kod:6s} veri yetersiz, atlaniyor")
            continue

        seri = []
        for _, r in df.iterrows():
            v = r.get("VALUE")
            t = r.get("DATE")
            if v is None or pd.isna(v) or t is None:
                continue
            try:
                tarih_str = pd.to_datetime(t).strftime("%Y-%m-%d")
            except Exception:
                continue
            seri.append({"tarih": tarih_str, "kapanis": round(float(v), 2)})
        if len(seri) < 30:
            continue

        cikti = {"kod": kod, "ad": ad, "guncelleme": now_iso, "gun_sayisi": len(seri), "seri": seri}
        (hedef_klasor / f"{kod}.json").write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")
        ok += 1
        print(f"  {kod:6s} {len(seri)} gun -> tamam")

    print(f"\nTamamlandi: {ok}/{len(ENDEKSLER)} endeks -> {hedef_klasor}")


if __name__ == "__main__":
    main()
