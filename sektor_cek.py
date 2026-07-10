# -*- coding: utf-8 -*-
"""
GNC Insight - BIST Sektor Verisi Cekici (Is Yatirim kaynagi) - DAYANIKLI
GitHub Actions tarafindan zamanli calistirilir. Tum BIST sektor endekslerini
TEK TEK (retry ile) ceker, gunluk/haftalik/aylik getirileri hesaplar ve panelin
okudugu statik dosyayi (gnc-panel/sektor_verisi.json) yazar.

DAYANIKLILIK:
- Endeksler tek tek cekilir; biri timeout olsa digerleri devam eder.
- Her endekste 3 defa tekrar denenir (Is Yatirim gecici yavaslamalarina karsi).
- Taze gelmeyen endeks icin ELDEKI ESKI veri korunur (bosluk olusmaz).
- Hic taze veri gelmezse mevcut dosyaya DOKUNULMAZ (panel eski saglam veriyle calisir).
- guncelleme UTC-farkli yazilir (panelde saat kaymasi olmaz).
"""

import json
import time
from datetime import datetime, timedelta, timezone
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
DENEME = 3          # her endeks icin tekrar sayisi
BEKLE = 2           # denemeler arasi saniye


def yuzde(son, onceki):
    if son is None or onceki is None or onceki == 0:
        return None
    return round((son / onceki - 1) * 100, 2)


def getiri_hesapla(kapanis, tarih):
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


def cek_tek(kod, baslangic, bitis):
    """Tek endeksi retry ile ceker; basarisizsa None."""
    for i in range(DENEME):
        try:
            df = fetch_index_data(indices=[kod], start_date=baslangic, end_date=bitis)
            if df is not None and len(df):
                return df
        except Exception as e:
            print(f"  {kod:6s} deneme {i+1}/{DENEME} hata: {str(e)[:70]}")
        if i < DENEME - 1:
            time.sleep(BEKLE)
    return None


def eski_yukle(hedef):
    """Mevcut sektor_verisi.json'u {kod: kayit} olarak yukler (koruma icin)."""
    eski = {}
    if hedef.exists():
        try:
            data = json.loads(hedef.read_text(encoding="utf-8"))
            for e in data.get("endeksler", []):
                if e.get("kod"):
                    eski[e["kod"]] = e
        except Exception as e:
            print(f"Eski dosya okunamadi: {e}")
    return eski


def main():
    bugun = datetime.now()
    baslangic = (bugun - timedelta(days=400)).strftime("%d-%m-%Y")
    bitis = bugun.strftime("%d-%m-%Y")

    hedef = Path(__file__).parent / "gnc-panel" / "sektor_verisi.json"
    hedef.parent.mkdir(parents=True, exist_ok=True)
    eski = eski_yukle(hedef)

    print(f"{len(ENDEKSLER)} endeks tek tek cekiliyor (Is Yatirim)...")
    sonuclar = []
    taze_sayi = 0

    for kod, ad, tip in ENDEKSLER:
        df = cek_tek(kod, baslangic, bitis)
        if df is not None:
            alt = df[df["INDEX"] == kod].sort_values("DATE")
            if len(alt) >= 2:
                kapanis = [float(v) for v in alt["VALUE"].tolist()]
                tarih = list(alt["DATE"].tolist())
                kayit = {"kod": kod, "ad": ad, "tip": tip}
                kayit.update(getiri_hesapla(kapanis, tarih))
                sonuclar.append(kayit)
                taze_sayi += 1
                print(f"  {kod:6s} tamam ({len(alt)} gun)")
                continue
        # Taze gelmedi -> eski veriyi koru
        if kod in eski:
            korunan = dict(eski[kod])
            korunan["ad"] = ad
            korunan["tip"] = tip
            sonuclar.append(korunan)
            print(f"  {kod:6s} taze gelmedi -> eski veri korundu")
        else:
            kayit = {"kod": kod, "ad": ad, "tip": tip, "son_deger": None, "hata": True}
            kayit.update({d: None for d in DONEMLER})
            sonuclar.append(kayit)
            print(f"  {kod:6s} veri yok (eski de yok)")

    # Hic taze veri gelmediyse mevcut dosyaya dokunma (panel eski saglam veriyle calissin)
    if taze_sayi == 0:
        print("\nHic taze veri gelmedi. Mevcut dosya KORUNUYOR (yazilmadi).")
        return

    # XU100'e gore rolatif
    xu = next((s for s in sonuclar if s["kod"] == "XU100"), None)
    for s in sonuclar:
        for d in DONEMLER:
            if xu and s.get(d) is not None and xu.get(d) is not None:
                s["rol_" + d] = round(s[d] - xu[d], 2)
            else:
                s["rol_" + d] = None

    cikti = {
        "guncelleme": datetime.now(timezone.utc).isoformat(),
        "kaynak": "Is Yatirim",
        "endeksler": sonuclar,
    }
    hedef.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")
    print(f"\nTamamlandi: {taze_sayi}/{len(ENDEKSLER)} endeks TAZE -> {hedef}")


if __name__ == "__main__":
    main()
