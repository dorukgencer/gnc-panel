# -*- coding: utf-8 -*-
"""
GNC Insight - Makro Rejim Verisi Cekici (FRED)
DXY (genis dolar endeksi), ABD 10 yillik tahvil faizi, Turkiye 10 yillik
tahvil faizi (OECD) ve Turkiye TUFE YoY serilerini FRED'den 10 yillik,
AYLIK olarak ceker; gnc-panel/makro_gecmis.json'a yazar.

Bu dosya "Modelleme" sayfasinin ham malzemesidir: guncel ortamin gecmis
yillarin hangisine benzedigini hesaplamak icin kullanilir (TCMB politika
faizi ayri dosyadan, faiz_gecmis.json'dan gelir).

GEREKLI: FRED_API_KEY ortam degiskeni (GitHub Actions secret olarak
eklenmelidir - Netlify'daki ile ayni key kullanilabilir).
"""

import json
import os
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

KLASOR = Path(__file__).parent
HEDEF = KLASOR / "gnc-panel" / "makro_gecmis.json"

# FRED seri kodlari - hepsi ucretsiz, dogrulanmis:
SERILER = {
    "dxy":    {"kod": "DTWEXBGS",         "ad": "Dolar Endeksi (geniş)",   "birim": "endeks"},
    "us10y":  {"kod": "DGS10",            "ad": "ABD 10Y Tahvil",          "birim": "%"},
    "tr10y":  {"kod": "IRLTLT01TRM156N",  "ad": "Türkiye 10Y Tahvil",      "birim": "%"},
    "tufe":   {"kod": "CPALTT01TRM659N",  "ad": "Türkiye TÜFE (yıllık %)", "birim": "%"},
    "vix":    {"kod": "VIXCLS",           "ad": "VIX (Volatilite Endeksi)","birim": "endeks"},
    "nasdaq": {"kod": "NASDAQCOM",        "ad": "Nasdaq Composite",        "birim": "endeks"},
}


def _key():
    k = os.environ.get("FRED_API_KEY", "").strip()
    if not k:
        raise SystemExit("FRED_API_KEY ortam degiskeni bulunamadi (GitHub secret olarak ekle).")
    return k


def fred_cek(seri_kod, api_key, baslangic):
    """FRED'den aylik ortalama seri ceker -> [{'tarih':'YYYY-MM','deger':float}] yeni->eski."""
    params = urllib.parse.urlencode({
        "series_id": seri_kod,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": baslangic,
        "frequency": "m",              # aylik
        "aggregation_method": "avg",   # gunluk serilerde ay ortalamasi
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
            deger = round(float(v), 4)
        except ValueError:
            continue
        seri.append({"tarih": obs["date"][:7], "deger": deger})
    seri.sort(key=lambda x: x["tarih"], reverse=True)
    print(f"  {seri_kod}: {len(seri)} aylik gozlem (son: {seri[0]['tarih'] if seri else '-'})")
    return seri


def main():
    api_key = _key()
    baslangic = (datetime.now() - timedelta(days=365 * 20)).strftime("%Y-%m-%d")

    print("FRED makro serileri cekiliyor...")
    cikti_seriler = {}
    with ThreadPoolExecutor(max_workers=6) as havuz:
        gelecekler = {havuz.submit(fred_cek, tanim["kod"], api_key, baslangic): (anahtar, tanim) for anahtar, tanim in SERILER.items()}
        for gelecek in as_completed(gelecekler):
            anahtar, tanim = gelecekler[gelecek]
            try:
                seri = gelecek.result()
            except Exception as e:
                print(f"  {tanim['kod']}: hata {str(e)[:60]}")
                seri = []
            cikti_seriler[anahtar] = {
                "ad": tanim["ad"],
                "seri_kod": tanim["kod"],
                "birim": tanim["birim"],
                "seri": seri,
            }

    bos_olanlar = [k for k, v in cikti_seriler.items() if not v["seri"]]
    if len(bos_olanlar) == len(SERILER):
        # TOPLAM basarisizlik: sessizce return etmek yerine gercek hata firlat.
        # Boylece GitHub Actions bu calismayi "basarisiz" isaretler ve (varsayilan
        # ayarlar acikken) sana otomatik e-posta gider. Kismi basarisizlikta
        # (bazi seriler geldi) boyle yapmiyoruz - o normal, alarm yorgunlugu
        # yaratmasin diye sessiz UYARI olarak kaliyor (asagida).
        raise SystemExit("HICBIR seri gelmedi (FRED tamamen erisilemez oldu ya da API key gecersiz). Dosya yazilmadi, mevcut korunuyor.")

    cikti = {
        "guncelleme": datetime.now().isoformat(),
        "kaynak": "FRED (St. Louis Fed)",
        "not": "Aylik seriler, gunluk seriler ay ortalamasina indirgenmistir. Modelleme sayfasinin ham verisidir.",
        "seriler": cikti_seriler,
    }
    HEDEF.parent.mkdir(parents=True, exist_ok=True)
    HEDEF.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")
    print(f"\nTamamlandi -> {HEDEF}")
    if bos_olanlar:
        print(f"  UYARI: su seriler bos geldi: {', '.join(bos_olanlar)}")


if __name__ == "__main__":
    main()
