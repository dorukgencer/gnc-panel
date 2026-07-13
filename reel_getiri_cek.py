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
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import borsapy as bp
import requests

KLASOR = Path(__file__).parent
HEDEF = KLASOR / "gnc-panel" / "deflator.json"
HEDEF_FAIZ = KLASOR / "gnc-panel" / "faiz_gecmis.json"

TUFE_SERI = "TP.FG.J0"          # TUFE genel endeks (2003=100), aylik - TCMB EVDS (kacinilmaz, Turkiye'nin kendi verisi)
# USD_SERI ve ALTIN_SERI ARTIK KULLANILMIYOR (EVDS yerine Yahoo Finance'ten
# hesaplaniyor - bkz. _yahoo_kimlik/_yahoo_aylik_cek). Turkiye kaynaklarina
# guven sinirli oldugu icin, Turkiye'ye ozgu olmayan (USD/TRY, ons altin)
# veriler artik uluslararasi/global kaynaktan geliyor.
GRAM_ONS = 31.1034768


def _key():
    k = os.environ.get("EVDS_API_KEY", "").strip()
    if not k:
        raise SystemExit("EVDS_API_KEY ortam degiskeni bulunamadi (GitHub secret).")
    return k


_YAHOO_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def _yahoo_kimlik():
    """Yahoo Finance cerez+crumb al (sektor.js/kuresel.js'teki AYNI mantik,
    Python tarafinda). Ons altin (XAUUSD=X) ve USD/TRY (TRY=X) icin kullanilir -
    Turkiye kaynagina guven sinirli oldugu icin bu ikisi artik global/Yahoo'dan.
    TESHIS: basarisizlik durumunda durum kodu ve ham yaniti loglar (GitHub Actions'in
    IP'sinin Yahoo tarafindan engellenip engellenmedigini gormek icin)."""
    session = requests.Session()
    session.headers.update({"User-Agent": _YAHOO_UA})
    try:
        session.get("https://fc.yahoo.com/", timeout=15)
    except Exception as e:
        print(f"    [TESHIS] fc.yahoo.com cerez istegi hata: {e}")
    crumb = None
    try:
        r = session.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=15)
        if r.status_code == 200 and "<" not in r.text:
            crumb = r.text.strip()
        else:
            print(f"    [TESHIS] crumb alinamadi - durum kodu: {r.status_code}, ilk 150 karakter: {r.text[:150]!r}")
    except Exception as e:
        print(f"    [TESHIS] crumb istegi hata: {e}")
        pass
    return session, crumb


def _yahoo_aylik_cek(sembol, session, crumb):
    """Yahoo'dan uzun donem AYLIK kapanis serisi -> [{'tarih':'YYYY-MM','deger':float}] yeni->eski."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sembol}"
    params = {"range": "20y", "interval": "1mo"}
    if crumb:
        params["crumb"] = crumb
    veri = None
    for deneme in range(3):
        try:
            r = session.get(url, params=params, timeout=30)
            if r.status_code == 429:
                bekle = 5 * (deneme + 1)
                print(f"  {sembol}: 429 (rate limit), {bekle}sn bekleyip tekrar denenecek ({deneme+1}/3)")
                time.sleep(bekle)
                continue
            if r.status_code != 200:
                print(f"  {sembol}: cekilemedi - HTTP {r.status_code}, ilk 200 karakter: {r.text[:200]!r}")
                return []
            veri = r.json()
            break
        except Exception as e:
            print(f"  {sembol}: cekilemedi ({e})")
            return []
    if veri is None:
        print(f"  {sembol}: 3 denemede de basarisiz (rate limit devam ediyor)")
        return []
    try:
        result = veri["chart"]["result"][0]
        zamanlar = result["timestamp"]
        kapanislar = result["indicators"]["quote"][0]["close"]
    except Exception as e:
        print(f"  {sembol}: yanit ayristirilamadi ({e})")
        return []

    tekil = {}
    for t, c in zip(zamanlar, kapanislar):
        if c is None:
            continue
        ay = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m")
        tekil[ay] = round(float(c), 4)  # ayni aya birden fazla nokta duserse SON deger kalir
    seri = [{"tarih": t, "deger": d} for t, d in tekil.items()]
    seri.sort(key=lambda x: x["tarih"], reverse=True)
    print(f"  {sembol}: {len(seri)} aylik gozlem")
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

    # USD/TRY ve ons altin Turkiye'ye OZGU degil - global piyasa fiyati.
    # Turkiye kaynagina guven sinirli oldugu icin Yahoo Finance'ten (uluslararasi,
    # likit, standart) cekilir; gram altin TL kendimiz hesaplariz.
    print("Yahoo Finance'ten USD/TRY ve ons altin cekiliyor...")
    session, crumb = _yahoo_kimlik()
    # Sirali cekiyoruz (paralel degil) - 2 sembol bile olsa, ayni IP'den ust uste
    # istekler rate limit tetikleyebiliyor (makro_cek.py'de 4 sembolde dogrulandi).
    usdtry_seri = _yahoo_aylik_cek("TRY=X", session, crumb)
    time.sleep(3)
    xau_seri = _yahoo_aylik_cek("XAUUSD=X", session, crumb)

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
