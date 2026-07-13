# -*- coding: utf-8 -*-
"""
GNC Insight - Reel Getiri Deflatoru + TCMB Politika Faizi Cekici
Enflasyon (TUFE), USD/TRY, gram altin VE TCMB politika faizi (1 hafta repo)
aylik serilerini ceker; deflator.json'a yazar.

ONEMLI (Tem 2026): Bu script eskiden `evds` (PyPI) paketini kullaniyordu.
TCMB, EVDS altyapisini 2025 sonunda evds3.tcmb.gov.tr'ye tasidi ve eski
evds2.tcmb.gov.tr/service/evds/ uc noktalarini tamamen kapatti. Eski `evds`
paketi artik CALISMIYOR (302 -> SPA HTML donuyor, sessizce bos veri
uretiyordu - "Ocak sonrasi veri yok" sorununun kok nedeni buydu).
Bu yuzden `borsapy` kutuphanesine tasindi (repo'da zaten sektor_hisseler_cek.py
ve turkiye_cek.py'de kullaniliyor, EVDS v3'u sarmalıyor).

Kaynak: TCMB EVDS v3 (borsapy uzerinden). Anahtar EVDS_API_KEY ortam
degiskeninden okunur (GitHub Actions secret) - borsapy bu ismi otomatik tanir.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import borsapy as bp

KLASOR = Path(__file__).parent
HEDEF = KLASOR / "gnc-panel" / "deflator.json"
HEDEF_FAIZ = KLASOR / "gnc-panel" / "faiz_gecmis.json"

TUFE_SERI = "TP.FG.J0"          # TUFE genel endeks (2003=100), aylik - TCMB EVDS
USD_SERI = "TP.DK.USD.A.YTL"    # USD/TRY alis kuru - TCMB EVDS
GOLD_FRED = "GOLDAMGBD228NLBM"  # Ons altin (LBMA, USD) - FRED
# NOT (13 Tem 2026): USD/TRY ve altin ONCEDEN Yahoo Finance'ten cekiliyordu
# ("uluslararasi, likit, standart kaynak" gerekcesiyle) ama GitHub Actions'ta
# Yahoo SUREKLI 429 (Too Many Requests) verdi - bekleme/retry ile de cozulmedi,
# yani muhtemelen IP bazli engelleme. Artik ikisi de EVDS/FRED'den - ayni script
# icinde zaten sorunsuz calisan altyapilar.
GRAM_ONS = 31.1034768


def _key():
    k = os.environ.get("EVDS_API_KEY", "").strip()
    if not k:
        raise SystemExit("EVDS_API_KEY ortam degiskeni bulunamadi (GitHub secret).")
    return k


def _fred_key():
    k = os.environ.get("FRED_API_KEY", "").strip()
    if not k:
        raise SystemExit("FRED_API_KEY ortam degiskeni bulunamadi (GitHub secret).")
    return k


def _fred_aylik_cek(seri_kod, baslangic):
    """FRED'den aylik (gunluk seriler icin ay ortalamasi) veri ceker.
    Ons altin (GOLDAMGBD228NLBM) icin kullanilir - Yahoo'nun GitHub Actions'ta
    surekli 429 vermesi uzerine (13 Tem 2026'da dogrulandi) FRED'e gecildi."""
    import urllib.request
    import urllib.parse
    params = urllib.parse.urlencode({
        "series_id": seri_kod, "api_key": _fred_key(), "file_type": "json",
        "observation_start": baslangic, "frequency": "m", "aggregation_method": "avg",
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


def _df_to_seri(df, deger_kolon_ipucu=None):
    """borsapy DataFrame -> [{'tarih':'YYYY-MM','deger':float}, ...] (yeni->eski).
    Tarih index (DatetimeIndex) veya ilk kolon olabilir; deger kolonunu
    esnek bulur (tam kolon adini bilmeden calismasi icin - borsapy surumden
    surume kolon adini degistirebilir)."""
    if df is None or not len(df):
        return []
    df = df.reset_index()
    kolonlar = list(df.columns)
    tarih_kol = kolonlar[0]
    for k in kolonlar:
        if str(k).lower() in ("tarih", "date", "index"):
            tarih_kol = k
            break
    deger_kol = None
    if deger_kolon_ipucu:
        for k in kolonlar:
            if deger_kolon_ipucu.lower() in str(k).lower():
                deger_kol = k
                break
    if deger_kol is None:
        adaylar = [k for k in kolonlar if k != tarih_kol]
        if not adaylar:
            return []
        deger_kol = adaylar[0]

    seri = []
    for _, r in df.iterrows():
        try:
            v = float(r[deger_kol])
        except (TypeError, ValueError):
            continue
        if v != v:  # NaN kontrolu
            continue
        try:
            t = str(r[tarih_kol])[:10]
            yil, ay = t.split("-")[0], t.split("-")[1]
        except Exception:
            continue
        seri.append({"tarih": f"{yil}-{ay}", "deger": round(v, 4)})
    # ay bazinda tekillestir (gunluk veri aylik'a indirgenmisse coklanabilir) - SON degeri tut
    tekil = {}
    for s in seri:
        tekil[s["tarih"]] = s["deger"]
    seri = [{"tarih": t, "deger": d} for t, d in tekil.items()]
    seri.sort(key=lambda x: x["tarih"], reverse=True)
    return seri


def _seri_cek(kod, baslangic, deger_ipucu=None):
    """Tek EVDS serisini aylik ceker. Hata olursa bos liste doner (pipeline kirilmaz)."""
    try:
        ev = bp.EVDS()
        s = ev.series(kod)
        df = s.history(start=baslangic, frequency="monthly", aggregation="avg")
        seri = _df_to_seri(df, deger_ipucu)
        print(f"  {kod}: {len(seri)} aylik gozlem")
        return seri
    except Exception as e:
        print(f"  {kod}: cekilemedi ({e})")
        return []


def _yuzde(son, onceki):
    if son is None or onceki in (None, 0):
        return None
    return round((son / onceki - 1) * 100, 2)


def _ay_geri(seri, n):
    return seri[n]["deger"] if len(seri) > n else None


def _ybb_baz(seri):
    if not seri:
        return None
    son_yil = int(seri[0]["tarih"][:4])
    aralik = f"{son_yil - 1}-12"
    for x in seri:
        if x["tarih"] == aralik:
            return x["deger"]
    bu_yil = [x for x in seri if x["tarih"][:4] == str(son_yil)]
    return bu_yil[-1]["deger"] if bu_yil else None


def _horizonlar(seri):
    if len(seri) < 2:
        return {"1a": None, "3a": None, "ybb": None, "1y": None, "son": None, "son_tarih": None}
    son = seri[0]["deger"]
    return {
        "son": son,
        "son_tarih": seri[0]["tarih"],
        "1a": _yuzde(son, _ay_geri(seri, 1)),
        "3a": _yuzde(son, _ay_geri(seri, 3)),
        "ybb": _yuzde(son, _ybb_baz(seri)),
        "1y": _yuzde(son, _ay_geri(seri, 12)),
    }


def main():
    bp.set_evds_key(_key())
    yil = datetime.now().year
    baslangic = f"{yil - 20}-01-01"  # 20 yil talep edilir; EVDS serisi o kadar eskiye gitmiyorsa zaten en eski gozlemden baslar, hata vermez

    # TUFE ve TCMB faizi Turkiye'nin KENDI verisi - kacinilmaz sekilde EVDS'ten.
    print("EVDS serileri cekiliyor (TÜFE, TCMB faizi - borsapy uzerinden)...")
    evds_sonuc = {}
    with ThreadPoolExecutor(max_workers=2) as havuz:
        gelecekler = {
            havuz.submit(_seri_cek, TUFE_SERI, baslangic): "tufe",
            havuz.submit(_seri_cek, "TP.APIFON4", baslangic): "faiz",
        }
        for gelecek in as_completed(gelecekler):
            anahtar = gelecekler[gelecek]
            try:
                evds_sonuc[anahtar] = gelecek.result()
            except Exception as e:
                print(f"  {anahtar}: hata {str(e)[:60]}")
                evds_sonuc[anahtar] = []
    tufe, faiz = evds_sonuc["tufe"], evds_sonuc["faiz"]

    # USD/TRY artik EVDS'ten (TP.DK.USD.A.YTL) - ayni script'te zaten calisan,
    # kanitlanmis borsapy/EVDS altyapisi yeniden kullaniliyor. Ons altin FRED'den
    # (GOLDAMGBD228NLBM). YAHOO ARTIK KULLANILMIYOR - GitHub Actions'ta surekli
    # 429 (Too Many Requests) verdigi ILK ISTEKTE bile dogrulandi (13 Tem 2026),
    # yani rate-limit degil muhtemelen IP bazli engelleme - beklemeyle cozulmuyor.
    print("USD/TRY (EVDS) ve ons altin (FRED) cekiliyor...")
    usdtry_seri = _seri_cek(USD_SERI, baslangic)
    xau_seri = _fred_aylik_cek(GOLD_FRED, baslangic)

    usd = usdtry_seri  # USD/TRY serisinin kendisi zaten "usd" olarak kullanilan sey
    usdtry_map = {s["tarih"]: s["deger"] for s in usdtry_seri}
    xau_map = {s["tarih"]: s["deger"] for s in xau_seri}
    ortak_aylar = sorted(set(usdtry_map) & set(xau_map), reverse=True)
    altin = [
        {"tarih": ay, "deger": round((xau_map[ay] / GRAM_ONS) * usdtry_map[ay], 4)}
        for ay in ortak_aylar
    ]
    print(f"  Gram altin (hesaplanmis): {len(altin)} aylik gozlem")

    if not tufe and not usd and not altin:
        raise SystemExit("TUFE/USD/Altin ucunun de bos geldi (EVDS ve/veya Yahoo erisilemez olabilir). deflator.json YAZILMADI, mevcut korunuyor.")

    cikti = {
        "guncelleme": datetime.now().isoformat(),
        "kaynak": "TÜFE: TCMB EVDS · USD/TRY ve Altın: Yahoo Finance (hesaplanmış)",
        "not": "Aylik seriler. Reel getiri = (1+nominal)/(1+deflator)-1. Gunluk/haftalik reel getiri anlamsizdir (enflasyon aylik). Gram altin, ons altin ($) x USD/TRY / 31.1034768 formuluyle hesaplanir (TCMB'nin kendi gram altin serisi yerine).",
        "deflatorler": {
            "tufe": {"ad": "TÜFE (Enflasyon)", "seri_kod": TUFE_SERI, **_horizonlar(tufe), "seri": tufe},
            "usd": {"ad": "USD/TRY", "seri_kod": "Yahoo:TRY=X", **_horizonlar(usd), "seri": usd},
            "altin": {"ad": "Gram Altın", "seri_kod": "Yahoo:XAUUSD=X x TRY=X (hesaplanmış)", **_horizonlar(altin), "seri": altin},
        },
    }
    HEDEF.parent.mkdir(parents=True, exist_ok=True)
    HEDEF.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")

    # Faiz gecmisini AYRI dosyaya yaz (yalnizca gercekten veri geldiyse)
    if faiz:
        faiz_cikti = {
            "guncelleme": datetime.now().isoformat(),
            "kaynak": "TCMB EVDS (borsapy)",
            "not": "TCMB Ağırlıklı Ortalama Fonlama Maliyeti (TP.APIFON4) - fiili politika faizi olarak kullanılır. Aylık, yeniden eskiye sıralı.",
            "seri": faiz,
        }
        HEDEF_FAIZ.write_text(json.dumps(faiz_cikti, ensure_ascii=False), encoding="utf-8")
    else:
        print("  UYARI: Faiz serisi (TP.APIFON4) bos geldi; faiz_gecmis.json YAZILMADI, mevcut korunuyor.")

    ozet = {k: v.get("1y") for k, v in cikti["deflatorler"].items()}
    print(f"\nTamamlandi -> {HEDEF}")
    print(f"  1Y degisim: TÜFE={ozet['tufe']}%  USD={ozet['usd']}%  Altın={ozet['altin']}%")
    if faiz:
        print(f"Faiz gecmisi -> {HEDEF_FAIZ} ({len(faiz)} aylik gozlem)")
    if not altin:
        print("  UYARI: Altin serisi bos geldi, kontrol et.")
    if not faiz:
        print("  UYARI: Faiz serisi (TP.APIFON4) bos geldi, seri kodu degismis olabilir.")


if __name__ == "__main__":
    main()
