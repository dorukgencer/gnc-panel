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

import requests

KLASOR = Path(__file__).parent
HEDEF = KLASOR / "gnc-panel" / "makro_gecmis.json"

# FRED seri kodlari - hepsi ucretsiz, dogrulanmis:
SERILER = {
    "dxy_genis":  {"kod": "DTWEXBGS",         "ad": "Dolar Endeksi (FED, geniş - 26 para birimi)", "birim": "endeks (2006=100)"},
    "tr10y":      {"kod": "IRLTLT01TRM156N",  "ad": "Türkiye 10Y Tahvil",      "birim": "%", "devre_disi": True},  # HTTP 400 - FRED'de bu seri gecerli degil (12 Tem 2026'da dogrulandi), guvenilir alternatif bulunamadi
    "tufe":       {"kod": "CPALTT01TRM659N",  "ad": "Türkiye TÜFE (yıllık %)", "birim": "%"},
    "buyume":     {"kod": "TURLOLITOAASTSAM", "ad": "Türkiye Öncü Gösterge Endeksi (OECD)", "birim": "endeks"},
    "breakeven":  {"kod": "T10YIE",           "ad": "ABD 10Y Breakeven Enflasyon", "birim": "%"},
    "fed_walcl":  {"kod": "WALCL",            "ad": "FED Bilançosu",           "birim": "milyon $"},
    "fed_tga":    {"kod": "WTREGEN",          "ad": "Hazine Genel Hesabı (TGA)", "birim": "milyon $"},
    "fed_rrp":    {"kod": "RRPONTSYD",        "ad": "Ters Repo (RRP)",         "birim": "milyar $ (DIKKAT: farkli birim)"},
    "tr_rezerv":  {"kod": "TRESEGTRM052N",    "ad": "Türkiye Toplam Rezerv (altın hariç, IMF/FRED)", "birim": "belirsiz - dogrula (bkz. asagidaki UYARI)"},
    "hy_oas":     {"kod": "BAMLH0A0HYM2",     "ad": "ABD Yüksek Getirili Kredi Spreadi (HY OAS)", "birim": "%", "not": "FRED bu seriyi Nisan 2026'dan itibaren sadece son 3 yilla sinirlandirdi"},
}
# NOT: DXY, US10Y, VIX, Nasdaq artik FRED'den DEGIL, YAHOO'dan cekiliyor
# (asagida yahoo_gunluk_fiyatlar()) - FRED'de aylik kisitliydi, Yahoo gunluk
# veriyor ve DXY'de zaten FRED'in "genis" endeksi ile karisan sorun yasamistik.


def _key():
    k = os.environ.get("FRED_API_KEY", "").strip()
    if not k:
        raise SystemExit("FRED_API_KEY ortam degiskeni bulunamadi (GitHub secret olarak ekle).")
    return k


_YAHOO_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def _yahoo_kimlik():
    """Yahoo Finance cerez+crumb al (reel_getiri_cek.py'deki AYNI, kanitlanmis mantik)."""
    session = requests.Session()
    session.headers.update({"User-Agent": _YAHOO_UA})
    try:
        session.get("https://fc.yahoo.com/", timeout=15)
    except Exception:
        pass
    crumb = None
    try:
        r = session.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=15)
        if r.status_code == 200 and "<" not in r.text:
            crumb = r.text.strip()
    except Exception:
        pass
    return session, crumb


def yahoo_aylik_endeks_cek(sembol, ad, olcek_kontrolu=None):
    """Yahoo Finance'ten herhangi bir endeks/gosterge sembolunu AYLIK ozetlenmis
    ceker (ay icindeki son islem gununun kapanisi). gercek_dxy_cek'in
    genellestirilmis hali - DXY, US10Y, VIX, Nasdaq hepsi bunu kullanir.

    olcek_kontrolu: (deger) -> deger  seklinde opsiyonel bir fonksiyon.
    Ornegin ^TNX icin "eger deger 15'ten buyukse muhtemelen x10 olcekli,
    10'a bol" gibi bir SAVUNMA amacli duzeltme icin kullanilir - ciplak
    gozle mantiksiz gorunen degerleri SESSIZCE degil, LOGLAYARAK duzeltir."""
    session, crumb = _yahoo_kimlik()
    params = {"range": "20y", "interval": "1mo"}
    if crumb:
        params["crumb"] = crumb
    try:
        r = session.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sembol}", params=params, timeout=30)
        data = r.json()
        result = data["chart"]["result"][0]
        zamanlar = result["timestamp"]
        kapanislar = result["indicators"]["quote"][0]["close"]
    except Exception as e:
        print(f"  {sembol} ({ad}): cekilemedi ({e})")
        return []
    from datetime import timezone as _tz
    tekil = {}
    for t, c in zip(zamanlar, kapanislar):
        if c is None:
            continue
        ay = datetime.fromtimestamp(t, tz=_tz.utc).strftime("%Y-%m")
        tekil[ay] = float(c)
    duzeltme_uygulandi = False
    if olcek_kontrolu:
        for ay in list(tekil.keys()):
            yeni = olcek_kontrolu(tekil[ay])
            if yeni != tekil[ay]:
                duzeltme_uygulandi = True
            tekil[ay] = yeni
    seri = [{"tarih": t, "deger": round(d, 4)} for t, d in tekil.items()]
    seri.sort(key=lambda x: x["tarih"], reverse=True)
    uyari = " [OLCEK DUZELTMESI UYGULANDI - kontrol et!]" if duzeltme_uygulandi else ""
    print(f"  {sembol} ({ad}): {len(seri)} aylik gozlem (son: {seri[0]['tarih'] if seri else '-'}, deger: {seri[0]['deger'] if seri else '-'}){uyari}")
    return seri


def _tnx_olcek_kontrolu(deger):
    """^TNX'in Yahoo'daki gosterim sayfasi degeri DOGRUDAN yuzde olarak
    gosteriyor (orn 4.569 = %4.569) - 12 Tem 2026'da dogrulandi. Ama ham
    chart API'sinin bunu farkli olcekte donma ihtimaline karsi: gercekci
    ABD 10Y getirisi hicbir zaman %15'i gecmez (modern tarihte), eger
    deger 15'ten buyukse x10 olcekli gelmis demektir, 10'a boluyoruz."""
    return deger / 10 if deger > 15 else deger


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

    print("FRED makro serileri cekiliyor (+ Yahoo'dan DXY/US10Y/VIX/Nasdaq)...")
    cikti_seriler = {}
    with ThreadPoolExecutor(max_workers=15) as havuz:
        gelecekler = {havuz.submit(fred_cek, tanim["kod"], api_key, baslangic): (anahtar, tanim) for anahtar, tanim in SERILER.items() if not tanim.get("devre_disi")}
        yahoo_gelecekler = {
            havuz.submit(yahoo_aylik_endeks_cek, "DX-Y.NYB", "Dolar Endeksi (ICE DXY, gerçek)"): "dxy",
            havuz.submit(yahoo_aylik_endeks_cek, "^TNX", "ABD 10Y Tahvil", _tnx_olcek_kontrolu): "us10y",
            havuz.submit(yahoo_aylik_endeks_cek, "^VIX", "VIX (Volatilite Endeksi)"): "vix",
            havuz.submit(yahoo_aylik_endeks_cek, "^IXIC", "Nasdaq Composite"): "nasdaq",
        }
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
        yahoo_birimler = {"dxy": "endeks", "us10y": "%", "vix": "endeks", "nasdaq": "endeks"}
        yahoo_adlar = {"dxy": "Dolar Endeksi (ICE DXY, gerçek - 6 para birimi)", "us10y": "ABD 10Y Tahvil (Yahoo)", "vix": "VIX (Volatilite Endeksi)", "nasdaq": "Nasdaq Composite"}
        for gelecek in as_completed(yahoo_gelecekler):
            anahtar = yahoo_gelecekler[gelecek]
            try:
                seri = gelecek.result()
            except Exception as e:
                print(f"  Yahoo {anahtar}: hata {str(e)[:60]}")
                seri = []
            cikti_seriler[anahtar] = {
                "ad": yahoo_adlar[anahtar],
                "seri_kod": f"Yahoo",
                "birim": yahoo_birimler[anahtar],
                "seri": seri,
            }
        if cikti_seriler.get("dxy", {}).get("seri"):
            print(f"    [KONTROL] Gercek DXY icin gercekci aralik ~95-108 olmali.")
        if cikti_seriler.get("us10y", {}).get("seri"):
            print(f"    [KONTROL] ABD 10Y icin gercekci aralik ~%2-6 olmali (10+ ise olcek hatasi).")

    aktif_seri_sayisi = sum(1 for tanim in SERILER.values() if not tanim.get("devre_disi")) + 4  # +4 = Yahoo DXY/US10Y/VIX/Nasdaq
    bos_olanlar = [k for k, v in cikti_seriler.items() if not v["seri"]]
    if len(bos_olanlar) == aktif_seri_sayisi:
        # TOPLAM basarisizlik: sessizce return etmek yerine gercek hata firlat.
        # Boylece GitHub Actions bu calismayi "basarisiz" isaretler ve (varsayilan
        # ayarlar acikken) sana otomatik e-posta gider. Kismi basarisizlikta
        # (bazi seriler geldi) boyle yapmiyoruz - o normal, alarm yorgunlugu
        # yaratmasin diye sessiz UYARI olarak kaliyor (asagida).
        raise SystemExit("HICBIR seri gelmedi (FRED tamamen erisilemez oldu ya da API key gecersiz). Dosya yazilmadi, mevcut korunuyor.")

    # ABD 10Y reel faiz = US10Y - Breakeven enflasyon (ikisi de aylik, ayni aylari eslestir)
    us10y_map = {s["tarih"]: s["deger"] for s in cikti_seriler.get("us10y", {}).get("seri", [])}
    breakeven_map = {s["tarih"]: s["deger"] for s in cikti_seriler.get("breakeven", {}).get("seri", [])}
    ortak_aylar = sorted(set(us10y_map) & set(breakeven_map), reverse=True)
    reel_faiz_seri = [{"tarih": ay, "deger": round(us10y_map[ay] - breakeven_map[ay], 3)} for ay in ortak_aylar]
    if reel_faiz_seri:
        cikti_seriler["us_reel_faiz"] = {
            "ad": "ABD 10Y Reel Faiz (US10Y - Breakeven)",
            "seri_kod": "hesaplanmis: DGS10 - T10YIE",
            "birim": "%",
            "seri": reel_faiz_seri,
        }
        print(f"  ABD 10Y reel faiz (hesaplanmis): {len(reel_faiz_seri)} aylik gozlem")

    # Fed net likidite = WALCL - WTREGEN - RRPONTSYD*1000
    # KRITIK: WALCL ve WTREGEN milyon $ cinsinden, RRPONTSYD MILYAR $ cinsinden geliyor
    # (FRED'in kendi belgelenmis birimleri). RRP'yi *1000 ile milyona cevirmeden
    # toplarsak sonuc ciddi sekilde yanlis (RRP'nin etkisi 1000 kat kucuk) cikar.
    walcl_map = {s["tarih"]: s["deger"] for s in cikti_seriler.get("fed_walcl", {}).get("seri", [])}
    tga_map = {s["tarih"]: s["deger"] for s in cikti_seriler.get("fed_tga", {}).get("seri", [])}
    rrp_map = {s["tarih"]: s["deger"] for s in cikti_seriler.get("fed_rrp", {}).get("seri", [])}
    ortak_aylar_likidite = sorted(set(walcl_map) & set(tga_map) & set(rrp_map), reverse=True)
    net_likidite_seri = []
    for ay in ortak_aylar_likidite:
        milyon = walcl_map[ay] - tga_map[ay] - (rrp_map[ay] * 1000)
        net_likidite_seri.append({"tarih": ay, "deger_trilyon_usd": round(milyon / 1_000_000, 3)})
    if net_likidite_seri:
        cikti_seriler["fed_net_likidite"] = {
            "ad": "FED Net Likidite (Bilanço - TGA - RRP)",
            "seri_kod": "hesaplanmis: WALCL - WTREGEN - RRPONTSYD*1000, trilyon $",
            "birim": "trilyon $",
            "seri": net_likidite_seri,
        }
        son = net_likidite_seri[0]
        print(f"  FED net likidite (hesaplanmis): {len(net_likidite_seri)} aylik gozlem, son deger: ${son['deger_trilyon_usd']} Tr")
        print(f"    [KONTROL] 2026 ortasi icin gercekci aralik ~$5-7 Tr olmali. Bu sayi cok farkliysa (orn. negatif, ya da 100+) birim hatasi olabilir, bildir.")

    if "tr_rezerv" in cikti_seriler and cikti_seriler["tr_rezerv"]["seri"]:
        son_rezerv = cikti_seriler["tr_rezerv"]["seri"][0]["deger"]
        print(f"  [UYARI] Turkiye rezervi (TRESEGTRM052N) son deger: {son_rezerv}")
        print(f"    Birim KESIN DOGRULANAMADI (dolar mi SDR mi belirsiz). TCMB'nin kendi acikladigi")
        print(f"    guncel rezerv (~$170-190 Milyar dolayinda) ile goz kontrolu yap: bu sayi milyon $ ise")
        print(f"    ~170000-190000 civarinda olmali. Farkli bir mertebedeyse (orn. 120000-140000) SDR olabilir,")
        print(f"    o zaman SDR->USD cevrimi (yaklasik x1.3-1.4) eklememiz gerekir - bana bildir.")

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
