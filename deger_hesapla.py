# -*- coding: utf-8 -*-
"""
GNC Insight - Sektor Bazinda F/K Hesaplayici (guncel + 5 yillik ortalama)
Mevcut finansal/*.json ve hisse_gecmis/*.json dosyalarindan - YENI VERI
CEKMEDEN - sektor bazinda F/K hesaplar.

YONTEM: F/K = Fiyat / Hisse Basina Kazanc (EPS)
"Hisse Basina Kazanc" kalemi finansal tablolarda zaten cumulatif-yillik
(/12 donemi = tam yil EPS) olarak mevcut - bu sayede PD ve hisse sayisi
(bedelli/bedelsiz sermaye artirimlarindan etkilenen, elimizde tarihsel
verisi olmayan bir deger) hic gerekmiyor. Fiyat / EPS = F/K, direkt.

- Guncel F/K: guncel fiyat / en son acikanan yillik (/12) EPS
- 5 yillik ortalama: son 5 yilin her birinin Aralik-sonu fiyati / o yilin
  yillik EPS'i hesaplanir, 5 deger ortalanir
- Sektor F/K'si = sektordeki sirketlerin F/K medyanidir (asiri degerlerden
  etkilenmesin diye ortalama degil medyan - buyume_hesapla.py ile ayni mantik)
- Negatif/sifir EPS'li sirketler F/K hesabina katilmaz (anlamsiz sonuc verir)
"""

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

KLASOR = Path(__file__).parent
FINANSAL_KLASOR = KLASOR / "gnc-panel" / "finansal"
GECMIS_KLASOR = KLASOR / "gnc-panel" / "hisse_gecmis"
HEDEF = KLASOR / "gnc-panel" / "degerleme_gecmis.json"

EPS_KALEMI = "Hisse Başına Kazanç"


def sektor_haritasi():
    try:
        veri = json.loads((KLASOR / "gnc-panel" / "sektor_hisseler.json").read_text(encoding="utf-8"))
        harita = {}
        for sektor_kod, hisseler in veri.get("hisseler", {}).items():
            for h in hisseler:
                harita[h["kod"]] = sektor_kod
        return harita
    except Exception:
        return {}


def kalem_bul(kalemler, ad):
    for k in kalemler:
        if k.get("ad") == ad:
            return k.get("degerler", {})
    return None


def yillik_donemler(degerler):
    yillik = {d: v for d, v in degerler.items() if d.endswith("/12") and v is not None}
    return sorted(yillik.items(), key=lambda x: x[0], reverse=True)


def fiyat_serisi_yukle(kod):
    yol = GECMIS_KLASOR / f"{kod}.json"
    if not yol.exists():
        return None, {}
    try:
        veri = json.loads(yol.read_text(encoding="utf-8"))
    except Exception:
        return None, {}
    seri = sorted(veri.get("seri", []), key=lambda s: s["tarih"])
    if not seri:
        return None, {}
    guncel = seri[-1]["kapanis"]
    yil_sonu_fiyat = {}
    for s in seri:
        yil, ay = s["tarih"][:4], s["tarih"][5:7]
        if ay == "12":
            yil_sonu_fiyat[yil] = s["kapanis"]
    return guncel, yil_sonu_fiyat


def main():
    if not FINANSAL_KLASOR.exists() or not GECMIS_KLASOR.exists():
        raise SystemExit("finansal/ veya hisse_gecmis/ klasoru bulunamadi. Once ilgili pipeline'lar calismis olmali.")

    sektor_map = sektor_haritasi()
    if not sektor_map:
        raise SystemExit("sektor_hisseler.json okunamadi, sektor eslemesi yapilamiyor.")

    dosyalar = list(FINANSAL_KLASOR.glob("*.json"))
    print(f"{len(dosyalar)} sirket finansal dosyasi bulundu.")

    sektor_fk_guncel = {}
    sektor_fk_5yil = {}
    guncel_islenen = 0
    besyil_islenen = 0

    for dosya in dosyalar:
        kod = dosya.stem
        sektor = sektor_map.get(kod)
        if not sektor:
            continue
        try:
            veri = json.loads(dosya.read_text(encoding="utf-8"))
        except Exception:
            continue
        kalemler = veri.get("kalemler", [])
        eps_degerler = kalem_bul(kalemler, EPS_KALEMI)
        if not eps_degerler:
            continue
        eps_yillik = yillik_donemler(eps_degerler)
        if not eps_yillik:
            continue

        guncel_fiyat, yil_sonu_fiyat = fiyat_serisi_yukle(kod)
        if guncel_fiyat is None:
            continue

        son_donem, son_eps = eps_yillik[0]
        if son_eps and son_eps > 0:
            fk = guncel_fiyat / son_eps
            if 0 < fk < 500:
                sektor_fk_guncel.setdefault(sektor, []).append(fk)
                guncel_islenen += 1

        yillik_fk_listesi = []
        for donem, eps in eps_yillik[:5]:
            yil = donem[:4]
            fiyat = yil_sonu_fiyat.get(yil)
            if fiyat and eps and eps > 0:
                fk_o_yil = fiyat / eps
                if 0 < fk_o_yil < 500:
                    yillik_fk_listesi.append(fk_o_yil)
        if len(yillik_fk_listesi) >= 2:
            sirket_ortalama = sum(yillik_fk_listesi) / len(yillik_fk_listesi)
            sektor_fk_5yil.setdefault(sektor, []).append(sirket_ortalama)
            besyil_islenen += 1

    if not sektor_fk_guncel:
        raise SystemExit("Hicbir sektor icin guncel F/K hesaplanamadi. EPS kalem adi degismis olabilir.")

    sonuc = {}
    tum_sektorler = set(sektor_fk_guncel) | set(sektor_fk_5yil)
    for sektor in tum_sektorler:
        guncel_liste = sektor_fk_guncel.get(sektor, [])
        besyil_liste = sektor_fk_5yil.get(sektor, [])
        if len(guncel_liste) < 3:
            continue
        girdi = {
            "fk_guncel_medyan": round(statistics.median(guncel_liste), 2),
            "sirket_sayisi_guncel": len(guncel_liste),
        }
        if len(besyil_liste) >= 3:
            girdi["fk_5yil_ortalama_medyan"] = round(statistics.median(besyil_liste), 2)
            girdi["sirket_sayisi_5yil"] = len(besyil_liste)
            girdi["sapma_yuzde"] = round((girdi["fk_guncel_medyan"] - girdi["fk_5yil_ortalama_medyan"]) / girdi["fk_5yil_ortalama_medyan"] * 100, 1)
        sonuc[sektor] = girdi

    cikti = {
        "guncelleme": datetime.now(timezone.utc).isoformat(),
        "not": (
            "F/K = Fiyat / Hisse Başına Kazanç (EPS), en son açıklanan YILLIK (/12) dönem kullanılır. "
            "Sektör F/K'si, sektördeki şirketlerin F/K medyanıdır. Negatif/sıfır kârlı şirketler hariç "
            "tutulur. 5 yıllık ortalama, her şirketin son 5 yılının yıl-sonu fiyat/EPS oranlarının "
            "kendi içindeki ortalaması alınıp, sektör genelinde medyanlanmasıyla bulunur. "
            "Sapma % = (güncel F/K - 5 yıllık ortalama F/K) / 5 yıllık ortalama F/K × 100. "
            "Tek başına alım-satım sinyali değildir, eğitim ve araştırma amaçlıdır."
        ),
        "sektorler": sonuc,
    }
    HEDEF.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")

    print(f"\nTamamlandi: {len(sonuc)} sektor -> {HEDEF}")
    print(f"  Guncel F/K icin islenen sirket: {guncel_islenen}, 5-yillik icin: {besyil_islenen}")
    for sek, veri in sorted(sonuc.items(), key=lambda x: x[1]["fk_guncel_medyan"]):
        sapma = veri.get("sapma_yuzde")
        sapma_str = f" sapma=%{sapma:+.1f}" if sapma is not None else " (5y veri yetersiz)"
        print(f"  {sek:8s} F/K={veri['fk_guncel_medyan']:6.1f}{sapma_str}")


if __name__ == "__main__":
    main()
