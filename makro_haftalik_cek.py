# -*- coding: utf-8 -*-
"""
GNC Insight - Makro Ortam Sayfasi icin HAFTALIK cozunurluklu veri cekici.
makro_cek.py'nin AYLIK verisinden AYRI - o dosyaya dokunmuyor, Ana Sayfa'daki
ledger'lari etkilemiyor. Bu script SADECE Makro Ortam sayfasinin interaktif
grafiklerini (1A/3A/6A/1Y/5Y periyot secici) besler.

Cikti: gnc-panel/makro_haftalik.json
Format: {"guncelleme":..., "not":..., "dates": ["YYYY-MM-DD", ...], "series": {...}}
(mockup'taki RAW.dates + RAW.series yapisiyla birebir, sadece tarih formati
DD.MM.YYYY yerine YYYY-MM-DD - JS tarafinda parseDate'i buna gore uyarlariz)

KAPSAM DISI (bu script bunlari CEKMEZ, ayri calisir):
- tcmb_faiz, tufe: EVDS'te zaten AYLIK - haftalik cozunurluk YOK, kaynak kisiti.
  Bu ikisi mevcut faiz_gecmis.json / deflator.json'dan ayrica okunacak
  (JS tarafinda birlestirilecek).
- tcmb_rezerv_brut, tcmb_rezerv_net: HENUZ dogru EVDS seri kodu bulunamadi,
  bu script'e dahil edilmedi - ayri bir teshis turu gerekiyor.

BILINEN KISIT: HY OAS (BAMLH0A0HYM2) FRED tarafindan Nisan 2026'dan itibaren
son 3 yilla sinirlandirildi (5 yil degil). 5Y gorunumde bu seri icin ilk 2 yil
bos kalacak - bu FRED'in kendi kisiti, cozulemez.
"""

import json
import time
import os
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

KLASOR = Path(__file__).parent
HEDEF = KLASOR / "gnc-panel" / "makro_haftalik.json"

FRED_SERILER = {
    "breakeven":      "T10YIE",   # us10y_real'i hesaplamak icin ara deger, ciktiya dahil edilmez
    "fed_walcl":       "WALCL",   # fed_net_liq'i hesaplamak icin ara deger
    "fed_tga":         "WTREGEN",
    "fed_rrp":         "RRPONTSYD",
    "hy_oas":         "BAMLH0A0HYM2",  # FRED Nisan 2026'dan itibaren bu seriyi son 3 yilla sinirladi (5 yil degil)
}
# us10y_nominal ve vix artik FRED'den DEGIL, YAHOO'dan (^TNX, ^VIX) - asagida.

_YAHOO_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def _key():
    k = os.environ.get("FRED_API_KEY", "").strip()
    if not k:
        raise SystemExit("FRED_API_KEY ortam degiskeni bulunamadi.")
    return k


def fred_gunluk_cek(seri_kod, api_key, baslangic):
    """FRED'den GUNLUK (haftalik degil) ceker - haftalik ornekleme JS tarafinda
    ya da asagida ayri bir adimda yapilacak, boylece en taze noktayi kaybetmeyiz."""
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


def _yahoo_kimlik():
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
    return session, crumb


def yahoo_gunluk_cek(sembol, session, crumb):
    params = {"range": "5y", "interval": "1d"}
    if crumb:
        params["crumb"] = crumb
    veri = None
    for deneme in range(3):
        try:
            r = session.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sembol}", params=params, timeout=30)
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
    seri = []
    for t, c in zip(zamanlar, kapanislar):
        if c is None:
            continue
        tarih = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        seri.append({"tarih": tarih, "deger": round(float(c), 4)})
    print(f"  {sembol}: {len(seri)} gunluk gozlem (son: {seri[-1]['tarih'] if seri else '-'})")
    return seri


def haftalik_orneklemeye_indirge(gunluk_seri, hedef_tarihler):
    """Gunluk seriyi, HER hedef (haftalik) tarih icin O TARIHTEN ONCEKI (dahil)
    EN SON gozlemi alarak haftalik seriye indirger - "forward fill" mantigi,
    finans verisinde standart (hafta sonu/tatil gununde veri olmayabilir)."""
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
    """Bugunden geriye, 7 gunde bir, hafta_sayisi kadar tarih uretir (eskiden yeniye)."""
    tarihler = [(bugun - timedelta(days=7 * i)) for i in range(hafta_sayisi)]
    tarihler.sort()
    return [t.strftime("%Y-%m-%d") for t in tarihler]


def main():
    api_key = _key()
    bugun = datetime.now(timezone.utc)
    baslangic_fred = (bugun - timedelta(days=365 * 5 + 30)).strftime("%Y-%m-%d")
    hedef_tarihler = haftalik_tarihler_uret(bugun, 260)

    print("FRED gunluk serileri cekiliyor (haftalik ornekleme icin)...")
    fred_ham = {}
    with ThreadPoolExecutor(max_workers=8) as havuz:
        gelecekler = {havuz.submit(fred_gunluk_cek, kod, api_key, baslangic_fred): anahtar for anahtar, kod in FRED_SERILER.items()}
        for gelecek in as_completed(gelecekler):
            anahtar = gelecekler[gelecek]
            try:
                fred_ham[anahtar] = gelecek.result()
            except Exception as e:
                print(f"  {anahtar}: hata {str(e)[:60]}")
                fred_ham[anahtar] = []

    print("Yahoo'dan gunluk DXY, US10Y, VIX ve USD/TRY cekiliyor (tek kimlik, sirali)...")
    session, crumb = _yahoo_kimlik()
    yahoo_hedefler = [("dxy", "DX-Y.NYB"), ("usdtry", "TRY=X"), ("us10y_nominal", "^TNX"), ("vix", "^VIX")]
    yahoo_ham = {}
    for i, (anahtar, sembol) in enumerate(yahoo_hedefler):
        if i > 0:
            time.sleep(3)  # ardisik istekler arasi nazik bekleme - rate limit tetiklememek icin
        yahoo_ham[anahtar] = yahoo_gunluk_cek(sembol, session, crumb)

    # ^TNX savunma kontrolu: Yahoo'nun gosterim sayfasi dogrudan yuzde
    # gosteriyor (12 Tem 2026'da dogrulandi) ama ham API farkli olcekte
    # gelirse (>15, gercekci olmayan bir ABD 10Y getirisi) 10'a boluyoruz.
    if yahoo_ham.get("us10y_nominal"):
        duzeltildi = 0
        for nokta in yahoo_ham["us10y_nominal"]:
            if nokta["deger"] > 15:
                nokta["deger"] = round(nokta["deger"] / 10, 4)
                duzeltildi += 1
        if duzeltildi:
            print(f"    [OLCEK DUZELTMESI] {duzeltildi} ^TNX noktasi >15 geldigi icin 10'a bolundu - kontrol et!")

    if not any(fred_ham.values()) and not any(yahoo_ham.values()):
        raise SystemExit("HICBIR seri gelmedi. Dosya yazilmadi, mevcut korunuyor.")

    series = {}
    series["us10y_nominal"] = haftalik_orneklemeye_indirge(yahoo_ham.get("us10y_nominal", []), hedef_tarihler)
    series["vix"] = haftalik_orneklemeye_indirge(yahoo_ham.get("vix", []), hedef_tarihler)
    series["hy_oas"] = haftalik_orneklemeye_indirge(fred_ham.get("hy_oas", []), hedef_tarihler)
    series["dxy"] = haftalik_orneklemeye_indirge(yahoo_ham.get("dxy", []), hedef_tarihler)
    series["usdtry"] = haftalik_orneklemeye_indirge(yahoo_ham.get("usdtry", []), hedef_tarihler)

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
            "tcmb_faiz ve tufe burada YOK - EVDS'te zaten aylik, ayri dosyalardan "
            "(faiz_gecmis.json, deflator.json) okunmali. tcmb_rezerv_brut/net "
            "HENUZ eklenmedi - EVDS seri kodu teshisi bekliyor. "
            "HY OAS (BAMLH0A0HYM2), FRED'in kendi kisiti geregi Nisan 2026'dan "
            "itibaren sadece son 3 yili kapsiyor - 5Y gorunumde ilk 2 yil bos olacak."
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
