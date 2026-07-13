# -*- coding: utf-8 -*-
"""
GNC Insight - TCMB Brut/Net Rezerv Kesif Script'i
"TCMB Brut Rezerv" (altin dahil toplam) ve "TCMB Net Rezerv" (swap haric)
icin dogru EVDS seri kodlarini KOR TAHMINLE bulmuyoruz - bu script, olasi
aday seri gruplarini EVDS'ten arayip LOGLAR, dogru kodu SEN (ya da ben bu
logu gorunce) secer.

Bu, HAO_PD ve yabanci akis icin kullandigimiz AYNI yontemdir: once kesfet,
sonra kesin kodu koda goml.

CALISTIRDIKTAN SONRA: log ciktisini bana yapistir, hangi serinin "brut rezerv"
hangisinin "net rezerv" oldugunu birlikte netlestiririz.
"""

import os
import borsapy as bp


def _key():
    k = os.environ.get("EVDS_API_KEY", "").strip()
    if not k:
        raise SystemExit("EVDS_API_KEY ortam degiskeni bulunamadi.")
    return k


def main():
    bp.set_evds_key(_key())
    ev = bp.EVDS()

    print("=" * 70)
    print("YONTEM 1: EVDS kategori/seri arama (borsapy destekliyorsa)")
    print("=" * 70)
    try:
        if hasattr(ev, "search"):
            sonuc = ev.search("rezerv")
            print(sonuc)
        elif hasattr(ev, "categories"):
            sonuc = ev.categories()
            print(sonuc)
        else:
            print("  borsapy.EVDS() nesnesinde 'search' ya da 'categories' metodu bulunamadi.")
            print(f"  Mevcut metodlar: {[m for m in dir(ev) if not m.startswith('_')]}")
    except Exception as e:
        print(f"  Arama basarisiz: {e}")

    print()
    print("=" * 70)
    print("YONTEM 2: Bilinen/olasi seri kodu ADAYLARINI tek tek dene")
    print("=" * 70)
    print("(Bu kodlar DOGRULANMAMIS tahminlerdir - sadece hangisinin gercekten")
    print(" veri dondurdugunu gormek icin deneniyor, sonuc otomatik kullanilmiyor)")
    print()

    adaylar = {
        "TP.RK.T1": "Toplam rezervler (aday - brut olabilir)",
        "TP.RK.SVAP1": "Swap rezervleri (aday)",
        "TP.RK.NET1": "Net rezerv (aday)",
        "TP.AB.A1": "Altin rezervi (aday)",
    }
    for kod, aciklama in adaylar.items():
        try:
            s = ev.series(kod)
            df = s.history(start="2026-01-01", frequency="weekly")
            if df is not None and len(df):
                print(f"  {kod} ({aciklama}): VERI GELDI, {len(df)} satir, son deger:")
                print(f"    {df.tail(1)}")
            else:
                print(f"  {kod} ({aciklama}): bos donen ama hata vermedi")
        except Exception as e:
            print(f"  {kod} ({aciklama}): HATA - {str(e)[:80]}")

    print()
    print("=" * 70)
    print("Bu loglari GNC Insight asistanina yapistir - dogru kodu birlikte netlestirelim.")
    print("=" * 70)


if __name__ == "__main__":
    main()
