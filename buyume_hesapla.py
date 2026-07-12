# -*- coding: utf-8 -*-
"""
GNC Insight - Sirket Buyume (Hasilat) Endeksi Hesaplayici
Mevcut gnc-panel/finansal/{KOD}.json dosyalarindan (zaten cekilmis, yeni bir
API cagrisi YOK) sirket hasilat buyumesini cikarir, agregatif bir "Buyume
Ekseni" endeksi uretir.

ONEMLI - KUMULATIF VERI: KAP/Is Yatirim finansal verileri KUMULATIF'tir
(2025/9 = yilin ilk 9 ayinin toplami, 2025/12 = tum yil). Bu yuzden "onceki
donem"e gore degil, AYNI DONEM TIPININ BIR ONCEKI YILINA gore buyume
hesaplanir (2025/9 vs 2024/9 gibi) - boylece kumulatif sifirlanmasi sorunu
(Ocak'ta yeniden 0'dan baslama) devreye girmez.

Finansal-disi sirketler: "Satis Gelirleri" kalemi kullanilir.
Bankalar (XBANK sektoru): "Satis Gelirleri" YOK, onun yerine
"III. NET FAIZ GELIRI/GIDERI (I - II)" kullanilir (bankanin hasilat karsiligi).

Sonuc: gnc-panel/buyume_gecmis.json - donem bazinda (donemler ayni
finansal/*.json dosyalarindaki gibi "YYYY/A" formatinda) medyan buyume yuzdesi.
Medyan kullanilir (ortalama degil) cunku birkac asiri deger (kur zarari
patlayan sirket gibi) butun endeksi bozmasin diye.
"""

import json
import statistics
from pathlib import Path

KLASOR = Path(__file__).parent
FINANSAL_KLASOR = KLASOR / "gnc-panel" / "finansal"
HEDEF = KLASOR / "gnc-panel" / "buyume_gecmis.json"

SATIS_KALEMI = "Satış Gelirleri"
BANKA_KALEMI = "III. NET FAİZ GELİRİ/GİDERİ (I - II)"


def banka_kodlari():
    """sektor_hisseler.json'daki XBANK listesini oku (bankalari ayirt etmek icin)."""
    try:
        veri = json.loads((KLASOR / "gnc-panel" / "sektor_hisseler.json").read_text(encoding="utf-8"))
        return {h["kod"] for h in veri.get("hisseler", {}).get("XBANK", [])}
    except Exception:
        return set()


def onceki_yil_donemi(donem):
    """'2025/9' -> '2024/9' (ayni donem tipi, bir onceki yil)."""
    try:
        yil, ay = donem.split("/")
        return f"{int(yil) - 1}/{ay}"
    except Exception:
        return None


def kalem_bul(kalemler, ad):
    for k in kalemler:
        if k.get("ad") == ad:
            return k.get("degerler", {})
    return None


def sirket_buyume_serisi(dosya_yolu, banka_mi):
    try:
        veri = json.loads(dosya_yolu.read_text(encoding="utf-8"))
    except Exception:
        return {}
    kalemler = veri.get("kalemler", [])
    aranan = BANKA_KALEMI if banka_mi else SATIS_KALEMI
    degerler = kalem_bul(kalemler, aranan)
    if not degerler:
        return {}

    sonuc = {}
    for donem, deger in degerler.items():
        if deger is None:
            continue
        onceki_donem = onceki_yil_donemi(donem)
        if not onceki_donem or onceki_donem not in degerler:
            continue
        onceki_deger = degerler[onceki_donem]
        if onceki_deger is None or onceki_deger == 0:
            continue
        buyume = (deger / onceki_deger - 1) * 100
        if -95 <= buyume <= 500:
            sonuc[donem] = buyume
    return sonuc


def main():
    if not FINANSAL_KLASOR.exists():
        raise SystemExit(f"{FINANSAL_KLASOR} bulunamadi. Once hisse_finansal_cek.py calismis olmali.")

    bankalar = banka_kodlari()
    dosyalar = list(FINANSAL_KLASOR.glob("*.json"))
    print(f"{len(dosyalar)} sirket finansal dosyasi bulundu ({len(bankalar)} banka).")

    donem_bazinda = {}
    islenen = 0
    for dosya in dosyalar:
        kod = dosya.stem
        banka_mi = kod in bankalar
        seri = sirket_buyume_serisi(dosya, banka_mi)
        if not seri:
            continue
        islenen += 1
        for donem, buyume in seri.items():
            donem_bazinda.setdefault(donem, []).append(buyume)

    if not donem_bazinda:
        raise SystemExit("Hicbir sirket icin buyume hesaplanamadi. Kalem adlari degismis olabilir.")

    sonuc = []
    for donem, degerler in donem_bazinda.items():
        if len(degerler) < 5:
            continue
        sonuc.append({
            "donem": donem,
            "medyan_buyume": round(statistics.median(degerler), 2),
            "ortalama_buyume": round(sum(degerler) / len(degerler), 2),
            "sirket_sayisi": len(degerler),
        })
    sonuc.sort(key=lambda x: x["donem"])

    cikti = {
        "not": (
            "Her donem, o donemin (KUMULATIF, orn. 9 aylik) hasilatinin bir onceki yilin "
            "AYNI donemine gore yuzde degisimidir. Finansal-disi sirketlerde 'Satis Gelirleri', "
            "bankalarda 'Net Faiz Geliri' kullanilir. Medyan, asiri degerlerden etkilenmez."
        ),
        "sirket_sayisi_islenen": islenen,
        "donemler": sonuc,
    }
    HEDEF.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")

    son3 = sonuc[-3:] if len(sonuc) >= 3 else sonuc
    print(f"\nTamamlandi: {len(sonuc)} donem, {islenen} sirket islendi -> {HEDEF}")
    for s in son3:
        print(f"  {s['donem']}: medyan %{s['medyan_buyume']} ({s['sirket_sayisi']} sirket)")


if __name__ == "__main__":
    main()
