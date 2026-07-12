# -*- coding: utf-8 -*-
"""
GNC Insight - Halka Aciklik Orani / Piyasa Degeri Kolon TESHISI (tek seferlik)
Amac: isyatirimhisse'nin fetch_stock_data() ciktisindaki TUM sutunlari,
hicbir varsayimda bulunmadan, ham haliyle goster. Boylece HAO_PD'nin
gercekten "halka aciklik oranli piyasa degeri" mi, yoksa baska bir sey mi
oldugunu VERIYE BAKARAK anlariz - tahmin etmeyiz (TCMB faizinde yasadigimiz
yanlis tahmin hatasini tekrarlamamak icin).

Birden fazla hisseyle test ediyoruz (banka + sanayi + yuksek/dusuk halka
aciklikli bilinen sirketler) ki HAO_PD ile PD arasinda GERCEKTEN fark var mi
gorelim - eger iki sutun her hissede birebir ayniysa, HAO_PD aslinda
duzeltme YAPMIYOR demektir.
"""

from isyatirimhisse import fetch_stock_data

# Bilinen halka aciklik oranlari FARKLI birkac hisse (cesitlilik icin):
# THYAO (yuksek halka aciklik ~%51), ASELS (devlet payı yuksek, dusuk halka aciklik ~%25),
# GARAN (BBVA payı var, orta), TUPRS (Koc payı yuksek, dusuk-orta)
TEST_HISSELER = ["THYAO", "ASELS", "GARAN", "TUPRS"]


def main():
    for kod in TEST_HISSELER:
        print(f"\n{'='*60}\n{kod}\n{'='*60}")
        try:
            df = fetch_stock_data(symbols=[kod], start_date="01-07-2026", end_date="12-07-2026")
        except Exception as e:
            print(f"  HATA: {e}")
            continue
        if df is None or not len(df):
            print("  Veri gelmedi.")
            continue

        print(f"  TUM SUTUNLAR: {list(df.columns)}")
        son_satir = df.iloc[-1]

        # Piyasa degeriyle iliskili olabilecek TUM sutunlari (adini tahmin etmeden) goster
        for kolon in df.columns:
            ku = str(kolon).upper()
            if "PD" in ku or "HAO" in ku or "SERMAYE" in ku or "HISSE_SAYI" in ku:
                print(f"    {kolon} = {son_satir[kolon]}")

    print(f"\n{'='*60}")
    print("KONTROL: Eger bir hissede PD ve HAO_PD sutunlari FARKLI degerler")
    print("gosteriyorsa, HAO_PD gercekten halka-aciklik-duzeltmesi yapiyordur.")
    print("ASELS gibi devlet payi yuksek hissede fark BUYUK olmali (PD >> HAO_PD).")
    print("Eger PD ile HAO_PD her hissede AYNI ise, sutun adi yaniltici demektir.")


if __name__ == "__main__":
    main()
