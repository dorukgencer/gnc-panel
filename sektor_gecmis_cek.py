# -*- coding: utf-8 -*-
"""
GNC Insight - BIST Sektor Rotasyon Verisi (gecmis)
Is Yatirim'dan ~10 yillik gunluk sektor endeksi verisini ceker, ay sonu
kapanislarina indirger, her sektor icin AYLIK % getiriyi hesaplar ve
gnc-panel/sektor_gecmis.json dosyasina yazar.

Bu dosya rotasyon/para akisi analizinin HAM MALZEMESIDIR. Rotasyon modulu
(hangi sektorden hangisine akis) sonra bu veriyi kullanacak.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from isyatirimhisse import fetch_index_data

# Sadece sektor endeksleri (ana grup/referans rotasyonda gerekmez ama XU100 kiyas icin dursun)
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
]

# Kac yil geriye gidilsin
YIL = 10


def aylik_getiri(df_kod):
    """Gunluk (DATE, VALUE) -> ay sonu kapanisi -> aylik % getiri listesi."""
    s = df_kod[["DATE", "VALUE"]].copy()
    s["DATE"] = pd.to_datetime(s["DATE"])
    s = s.set_index("DATE").sort_index()["VALUE"].astype(float)
    aysonu = s.resample("ME").last().dropna()
    getiri = aysonu.pct_change().dropna() * 100
    return [
        {"ay": ay.strftime("%Y-%m"), "getiri": round(float(g), 2)}
        for ay, g in getiri.items()
    ]


def main():
    kodlar = [k for k, _ in ENDEKSLER]
    bugun = datetime.now()
    baslangic = (bugun - timedelta(days=365 * YIL + 10)).strftime("%d-%m-%Y")
    bitis = bugun.strftime("%d-%m-%Y")

    print(f"{len(kodlar)} endeks icin {YIL} yillik gecmis cekiliyor...")
    df = fetch_index_data(indices=kodlar, start_date=baslangic, end_date=bitis)

    veri = {}
    for kod, ad in ENDEKSLER:
        alt = df[df["INDEX"] == kod]
        if len(alt) < 30:
            print(f"  {kod:6s} UYARI: yetersiz veri ({len(alt)})")
            continue
        veri[kod] = {"ad": ad, "aylik": aylik_getiri(alt)}
        print(f"  {kod:6s} {len(veri[kod]['aylik'])} ay")

    cikti = {
        "guncelleme": bugun.isoformat(),
        "kaynak": "Is Yatirim",
        "yil": YIL,
        "sektorler": veri,
    }
    hedef = Path(__file__).parent / "gnc-panel" / "sektor_gecmis.json"
    hedef.parent.mkdir(parents=True, exist_ok=True)
    hedef.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")
    print(f"\nTamamlandi: {len(veri)} sektor -> {hedef}")


if __name__ == "__main__":
    main()
