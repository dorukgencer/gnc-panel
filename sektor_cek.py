# -*- coding: utf-8 -*-
"""
GNC Insight - BIST Sektor Verisi Cekici (Is Yatirim kaynagi)
GitHub Actions tarafindan zamanli calistirilir. Tum BIST sektor endekslerini
ceker, gunluk/haftalik/aylik (+3ay, yilbasi) getirileri hesaplar ve panelin
okudugu statik dosyayi (gnc-panel/sektor_verisi.json) yazar.

Kaynak: Is Yatirim (isyatirimhisse). Yahoo yerine kullaniliyor cunku Is Yatirim
bulut sunuculari engellemiyor ve tum sektor endekslerini veriyor.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

from isyatirimhisse import fetch_index_data

ENDEKSLER = [
    ("XU100", "BIST 100", "referans"),
    ("XUSIN", "Sinai", "ana_grup"),
    ("XUMAL", "Mali", "ana_grup"),
    ("XUHIZ", "Hizmetler", "ana_grup"),
    ("XUTEK", "Teknoloji", "ana_grup"),
    ("XBANK", "Bankacilik", "sektor"),
    ("XSGRT", "Sigorta", "sektor"),
    ("XFINK", "Fin. Kiralama Faktoring", "sektor"),
    ("XHOLD", "Holding ve Yatirim", "sektor"),
    ("XGYO", "Gayrimenkul Yat. Ort.", "sektor"),
    ("XYORT", "Menkul Kiymet Yat. Ort.", "sektor"),
    ("XGIDA", "Gida ve Icecek", "sektor"),
    ("XKMYA", "Kimya Petrol Plastik", "sektor"),
    ("XMANA", "Metal Ana Sanayi", "sektor"),
    ("XMESY", "Metal Esya Makina", "sektor"),
    ("XTAST", "Tas Toprak (Cam Cimento)", "sektor"),
    ("XTEKS", "Tekstil ve Deri", "sektor"),
    ("XKAGT", "Orman Kagit Basim", "sektor"),
    ("XELKT", "Elektrik", "sektor"),
    ("XILTM", "Iletisim", "sektor"),
    ("XULAS", "Ulastirma", "sektor"),
    ("XTCRT", "Ticaret", "sektor"),
    ("XTRZM", "Turizm", "sektor"),
    ("XINSA", "Insaat ve Bayindirlik", "sektor"),
    ("XMADN", "Madencilik", "sektor"),
    ("XBLSM", "Bilisim", "sektor"),
    ("XSPOR", "Spor", "sektor"),
]

DONEMLER = ("g1", "h1", "a1", "a3", "ybb")


def yuzde(son, onceki):
    if son is None or onceki is None or onceki == 0:
        return None
    return round((son / onceki - 1) * 100, 2)


def getiri_hesapla(kapanis, tarih):
    """kapanis: kronolojik (eski->yeni) deger listesi, tarih: date listesi."""
    c = [(t, v) for t, v in zip(tarih, kapanis) if v is not None]
    if len(c) < 2:
        return {}
    tarih = [t for t, _ in c]
    c = [v for _, v in c]
    son = c[-1]

    def geri(n):
        return c[-1 - n] if len(c) > n else None

    son_yil = tarih[-1].year
    ilk_bu_yil = next((c[i] for i in range(len(tarih)) if tarih[i].year == son_yil), None)

    return {
        "son_deger": round(float(son), 2),
        "g1": yuzde(son, geri(1)),
        "h1": yuzde(son, geri(5)),
        "a1": yuzde(son, geri(21)),
        "a3": yuzde(son, geri(63)),
        "ybb": yuzde(son, ilk_bu_yil),
    }


def main():
    kodlar = [k for k, _, _ in ENDEKSLER]
    bugun = datetime.now()
    baslangic = (bugun - timedelta(days=400)).strftime("%d-%m-%Y")
    bitis = bugun.strftime("%d-%m-%Y")

    print(f"{len(kodlar)} endeks cekiliyor (Is Yatirim)...")
    df = fetch_index_data(indices=kodlar, start_date=baslangic, end_date=bitis)
    df = df.sort_values(["INDEX", "DATE"])

    sonuclar = []
    for kod, ad, tip in ENDEKSLER:
        alt = df[df["INDEX"] == kod]
        kayit = {"kod": kod, "ad": ad, "tip": tip}
        if len(alt) >= 2:
            kapanis = [float(v) for v in alt["VALUE"].tolist()]
            tarih = list(alt["DATE"].tolist())
            kayit.update(getiri_hesapla(kapanis, tarih))
            print(f"  {kod:6s} tamam ({len(alt)} gun)")
        else:
            kayit.update({d: None for d in DONEMLER})
            kayit["son_deger"] = None
            kayit["hata"] = True
            print(f"  {kod:6s} UYARI: veri gelmedi")
        sonuclar.append(kayit)

    # XU100'e gore rolatif
    xu = next((s for s in sonuclar if s["kod"] == "XU100"), None)
    for s in sonuclar:
        for d in DONEMLER:
            if xu and s.get(d) is not None and xu.get(d) is not None:
                s["rol_" + d] = round(s[d] - xu[d], 2)
            else:
                s["rol_" + d] = None

    cikti = {
        "guncelleme": bugun.isoformat(),
        "kaynak": "Is Yatirim",
        "endeksler": sonuclar,
    }

    hedef = Path(__file__).parent / "gnc-panel" / "sektor_verisi.json"
    hedef.parent.mkdir(parents=True, exist_ok=True)
    hedef.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")
    gelen = sum(1 for s in sonuclar if s.get("son_deger") is not None)
    print(f"\nTamamlandi: {gelen}/{len(sonuclar)} endeks -> {hedef}")


if __name__ == "__main__":
    main()
