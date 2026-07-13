# -*- coding: utf-8 -*-
"""
GNC Insight - Makro Ortam Sayfasi icin HAFTALIK cozunurluklu veri cekici.
makro_cek.py'nin AYLIK verisinden AYRI - o dosyaya dokunmuyor, Ana Sayfa'daki
ledger'lari etkilemiyor. Bu script SADECE Makro Ortam sayfasinin interaktif
grafiklerini (1A/3A/6A/1Y/5Y periyot secici) besler.

Cikti: gnc-panel/makro_haftalik.json
Format: {"guncelleme":..., "not":..., "dates": ["YYYY-MM-DD", ...], "series": {...}}

DEGISIKLIK (13 Tem 2026): Yahoo Finance TAMAMEN CIKARILDI. GitHub Actions'ta
ILK istekte bile 429 (Too Many Requests) verdi, bekleme/retry cozmedi -
muhtemelen IP bazli toptan engelleme (makro_cek.py ve reel_getiri_cek.py'de
de dogrulandi). us10y_nominal/vix artik FRED'den (guvenilir, hep calisti).
usdtry artik EVDS'ten (TP.DK.USD.A.YTL, borsapy uzerinden, GUNLUK cozunurlukte -
reel_getiri_cek.py'nin aylik kullandigi AYNI seri, farkli frekans).
dxy_genis, FED'in "genis" dolar endeksi (DTWEXBGS) - GERCEK ICE DXY DEGIL,
guvenilir bir alternatif bulunana kadar boyle kaliyor, sayfada acikca
"FED genis endeksi" diye etiketlenmeli.

KAPSAM DISI (bu script bunlari CEKMEZ, ayri calisir):
- tcmb_faiz, tufe: EVDS'te zaten AYLIK - haftalik cozunurluk YOK, kaynak kisiti.
  Bu ikisi mevcut faiz_gecmis.json / deflator.json'dan ayrica okunacak
  (JS tarafinda birlestirilecek).
- tcmb_rezerv_brut, tcmb_rezerv_net: HENUZ dogru EVDS seri kodu bulunamadi,
  bu script'e dahil edilmedi - ayri bir teshis turu gerekiyor.

BILINEN KISIT: HY OAS (BAMLH0A0HYM2) FRED tarafindan Nisan 2026'dan itibaren
son 3 yilla sinirlandirildi (5 yil degil). 5Y gorunumde bu seri icin ilk 2 yil
bos kalacak - bu FRED'in kendi kisiti, cozulemez.

GEREKLI: FRED_API_KEY VE EVDS_API_KEY ortam degiskenleri (ikisi de).
"""

import json
import os
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import borsapy as bp

KLASOR = Path(__file__).parent
HEDEF = KLASOR / "gnc-panel" / "makro_haftalik.json"

FRED_SERILER = {
    "us10y_nominal":  "DGS10",
    "vix":            "VIXCLS",
    "dxy_genis":      "DTWEXBGS",  # GERCEK ICE DXY DEGIL - bkz. dosya basi aciklama
    "breakeven":      "T10YIE",    # us10y_real'i hesaplamak icin ara deger, ciktiya dahil edilmez
    "fed_walcl":      "WALCL",     # fed_net_liq'i hesaplamak icin ara deger
    "fed_tga":        "WTREGEN",
    "fed_rrp":        "RRPONTSYD",
    "hy_oas":         "BAMLH0A0HYM2",
}


def _fred_key():
    k = os.environ.get("FRED_API_KEY", "").strip()
    if not k:
        raise SystemExit("FRED_API_KEY ortam degiskeni bulunamadi.")
    return k


def _evds_key():
    k = os.environ.get("EVDS_API_KEY", "").strip()
    if not k:
        raise SystemExit("EVDS_API_KEY ortam degiskeni bulunamadi.")
    return k


def fred_gunluk_cek(seri_kod, api_key, baslangic):
    """FRED'den GUNLUK (haftalik degil) ceker - haftalik ornekleme asagida ayri yapilir."""
    params = urllib.parse.urlencode({
        "series_id": seri_kod, "api_key": api_key, "file_type": "json",
        "observation_start": baslangic,
    })
    url = f"https://api.stlouisfed.org/fred/series/observations?{params}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"  {seri_kod}: cekilemedi ({e})")
        return []
    seri = []
    for obs in data.get("observations", []):
        v = obs.get("value")
        if v in (None, ".", ""):
            continue
        try:
            deger = float(v)
        except ValueError:
            continue
        seri.append({"tarih": obs["date"], "deger": deger})
    seri.sort(key=lambda x: x["tarih"])
    print(f"  {seri_kod}: {len(seri)} gunluk gozlem (son: {seri[-1]['tarih'] if seri else '-'})")
    return seri


def usdtry_gunluk_cek(baslangic):
    """EVDS'ten GUNLUK USD/TRY (TP.DK.USD.A.YTL, borsapy uzerinden) -
    reel_getiri_cek.py'nin aylik kullandigi AYNI seri, farkli frekans."""
    try:
        ev = bp.EVDS()
        s = ev.series("TP.DK.USD.A.YTL")
        df = s.history(start=baslangic, frequency="daily", aggregation="avg")
        if df is None or not len(df):
            print("  TP.DK.USD.A.YTL: veri gelmedi")
            return []
        df = df.reset_index()
        kolonlar = list(df.columns)
        tarih_kol = kolonlar[0]
        for k in kolonlar:
            if str(k).lower() in ("tarih", "date", "index"):
                tarih_kol = k
                break
        deger_kol = [k for k in kolonlar if k != tarih_kol][0]
        seri = []
        for _, row in df.iterrows():
            try:
                v = float(row[deger_kol])
            except (TypeError, ValueError):
                continue
            if v != v:
                continue
            tarih = str(row[tarih_kol])[:10]
            seri.append({"tarih": tarih, "deger": round(v, 4)})
        seri.sort(key=lambda x: x["tarih"])
        print(f"  TP.DK.USD.A.YTL: {len(seri)} gunluk gozlem (son: {seri[-1]['tarih'] if seri else '-'})")
        return seri
    except Exception as e:
        print(f"  TP.DK.USD.A.YTL: cekilemedi ({e})")
        return []


def haftalik_orneklemeye_indirge(gunluk_seri, hedef_tarihler):
    """Gunluk seriyi, HER hedef (haftalik) tarih icin O TARIHTEN ONCEKI (dahil)
    EN SON gozlemi alarak haftalik seriye indirger - "forward fill" mantigi."""
    if not gunluk_seri:
        return [None] * len(hedef_tarihler)
    harita = {s["tarih"]: s["deger"] for s in gunluk_seri}
    tum_tarihler = sorted(harita.keys())
    sonuc = []
    i = 0
    son_deger = None
    for hedef in hedef_tarihler:
        while i < len(tum_tarihler) and tum_tarihler[i] <= hedef:
            son_deger = harita[tum_tarihler[i]]
            i += 1
        sonuc.append(son_deger)
    return sonuc


def haftalik_tarihler_uret(bugun, hafta_sayisi=260):
    tarihler = [(bugun - timedelta(days=7 * i)) for i in range(hafta_sayisi)]
    tarihler.sort()
    return [t.strftime("%Y-%m-%d") for t in tarihler]


def main():
    api_key = _fred_key()
    bp.set_evds_key(_evds_key())
    bugun = datetime.now(timezone.utc)
    baslangic = (bugun - timedelta(days=365 * 5 + 30)).strftime("%Y-%m-%d")
    hedef_tarihler = haftalik_tarihler_uret(bugun, 260)

    print("FRED gunluk serileri cekiliyor...")
    fred_ham = {}
    with ThreadPoolExecutor(max_workers=8) as havuz:
        gelecekler = {havuz.submit(fred_gunluk_cek, kod, api_key, baslangic): anahtar for anahtar, kod in FRED_SERILER.items()}
        for gelecek in as_completed(gelecekler):
            anahtar = gelecekler[gelecek]
            try:
                fred_ham[anahtar] = gelecek.result()
            except Exception as e:
                print(f"  {anahtar}: hata {str(e)[:60]}")
                fred_ham[anahtar] = []

    print("EVDS'ten USD/TRY cekiliyor...")
    usdtry_ham = usdtry_gunluk_cek(baslangic)

    if not any(fred_ham.values()) and not usdtry_ham:
        raise SystemExit("HICBIR seri gelmedi. Dosya yazilmadi, mevcut korunuyor.")

    series = {}
    series["us10y_nominal"] = haftalik_orneklemeye_indirge(fred_ham.get("us10y_nominal", []), hedef_tarihler)
    series["vix"] = haftalik_orneklemeye_indirge(fred_ham.get("vix", []), hedef_tarihler)
    series["hy_oas"] = haftalik_orneklemeye_indirge(fred_ham.get("hy_oas", []), hedef_tarihler)
    series["dxy_genis"] = haftalik_orneklemeye_indirge(fred_ham.get("dxy_genis", []), hedef_tarihler)
    series["usdtry"] = haftalik_orneklemeye_indirge(usdtry_ham, hedef_tarihler)

    breakeven_hf = haftalik_orneklemeye_indirge(fred_ham.get("breakeven", []), hedef_tarihler)
    series["us10y_real"] = [
        round(a - b, 3) if a is not None and b is not None else None
        for a, b in zip(series["us10y_nominal"], breakeven_hf)
    ]

    walcl_hf = haftalik_orneklemeye_indirge(fred_ham.get("fed_walcl", []), hedef_tarihler)
    tga_hf = haftalik_orneklemeye_indirge(fred_ham.get("fed_tga", []), hedef_tarihler)
    rrp_hf = haftalik_orneklemeye_indirge(fred_ham.get("fed_rrp", []), hedef_tarihler)
    fed_net_liq = []
    for w, t, r in zip(walcl_hf, tga_hf, rrp_hf):
        if w is not None and t is not None and r is not None:
            fed_net_liq.append(round((w - t - r * 1000) / 1_000_000, 3))
        else:
            fed_net_liq.append(None)
    series["fed_net_liq"] = fed_net_liq

    bos_seriler = [k for k, v in series.items() if all(x is None for x in v)]

    cikti = {
        "guncelleme": datetime.now(timezone.utc).isoformat(),
        "not": (
            "Makro Ortam sayfasinin interaktif grafikleri icin HAFTALIK veri. "
            "Ana Sayfa'nin kullandigi makro_gecmis.json'dan (aylik) AYRIDIR. "
            "dxy_genis GERCEK ICE DXY DEGILDIR - FED'in genis dolar endeksi "
            "(DTWEXBGS), farkli olcekte. tcmb_faiz ve tufe burada YOK - EVDS'te "
            "zaten aylik, ayri dosyalardan (faiz_gecmis.json, deflator.json) "
            "okunmali. tcmb_rezerv_brut/net HENUZ eklenmedi. HY OAS, FRED'in "
            "kendi kisiti geregi Nisan 2026'dan itibaren sadece son 3 yili "
            "kapsiyor - 5Y gorunumde ilk 2 yil bos olacak."
        ),
        "dates": hedef_tarihler,
        "series": series,
    }
    HEDEF.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")

    print(f"\nTamamlandi: {len(hedef_tarihler)} haftalik nokta -> {HEDEF}")
    if bos_seriler:
        print(f"  UYARI: tamamen bos kalan seriler: {', '.join(bos_seriler)}")
    for k, v in series.items():
        dolu = sum(1 for x in v if x is not None)
        print(f"  {k}: {dolu}/{len(v)} nokta dolu")


if __name__ == "__main__":
    main()
