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
    # NOT (13 Tem 2026): dxy_genis, GERCEK ICE DXY DEGILDIR - FED'in "genis" 26
    # para birimli endeksi, farkli olcekte. Once bunun yerine Yahoo'dan gercek
    # DXY'yi cekmeyi denedik ama Yahoo, GitHub Actions'in IP'sini ILK ISTEKTE
    # BILE 429 (Too Many Requests) ile engelledi - bekleme/retry ile cozulmedi,
    # muhtemelen IP bazli toptan engelleme. Guvenilir bir gercek-DXY kaynagi
    # bulana kadar bu YAKLASIK deger kullaniliyor - sayfada "gerçek DXY" diye
    # SUNULMAMALI, acikca "FED genis endeksi" diye etiketlenmeli.
    "dxy_genis":  {"kod": "DTWEXBGS",         "ad": "Dolar Endeksi — FED geniş (26 para birimi)", "birim": "endeks (2006=100)", "uyari": "ICE DXY DEGILDIR; farkli olcek. Panelde bu adla gosterilmelidir."},
    "us10y":      {"kod": "DGS10",            "ad": "ABD 10Y Tahvil",          "birim": "%"},
    "us10y_reel": {"kod": "DFII10",           "ad": "ABD 10Y Reel Getiri (TIPS, resmi)", "birim": "%"},
    "vix":        {"kod": "VIXCLS",           "ad": "VIX (Volatilite Endeksi)","birim": "endeks"},
    "nasdaq":     {"kod": "NASDAQCOM",        "ad": "Nasdaq Composite",        "birim": "endeks"},
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
# YAHOO ARTIK KULLANILMIYOR (13 Tem 2026) - GitHub Actions'ta 429 ile
# engellendi, ILK istekte bile - bekleme/retry cozmedi. Tum seriler FRED'den.


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
    with ThreadPoolExecutor(max_workers=13) as havuz:
        gelecekler = {havuz.submit(fred_cek, tanim["kod"], api_key, baslangic): (anahtar, tanim) for anahtar, tanim in SERILER.items() if not tanim.get("devre_disi")}
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

    aktif_seri_sayisi = sum(1 for tanim in SERILER.values() if not tanim.get("devre_disi"))
    bos_olanlar = [k for k, v in cikti_seriler.items() if not v["seri"]]
    if len(bos_olanlar) == aktif_seri_sayisi:
        # TOPLAM basarisizlik: sessizce return etmek yerine gercek hata firlat.
        # Boylece GitHub Actions bu calismayi "basarisiz" isaretler ve (varsayilan
        # ayarlar acikken) sana otomatik e-posta gider. Kismi basarisizlikta
        # (bazi seriler geldi) boyle yapmiyoruz - o normal, alarm yorgunlugu
        # yaratmasin diye sessiz UYARI olarak kaliyor (asagida).
        raise SystemExit("HICBIR seri gelmedi (FRED tamamen erisilemez oldu ya da API key gecersiz). Dosya yazilmadi, mevcut korunuyor.")

    # ABD 10Y reel faiz: ONCELIK DFII10 (Hazine'nin RESMI TIPS-bazli reel getiri
    # serisi - hesaplamaya gerek yok, dogrudan yayinlanan gercek deger). DFII10
    # herhangi bir sebeple gelmezse (FRED erisim sorunu vb.) DGS10 - Breakeven
    # enflasyon YAKLASIK hesabina yedekte dusuluyor - iki yontem de ayni "reel
    # faiz" kavramini olcuyor ama DFII10 resmi, digeri turetilmis/yaklasik.
    if cikti_seriler.get("us10y_reel", {}).get("seri"):
        cikti_seriler["us_reel_faiz"] = {
            "ad": "ABD 10Y Reel Faiz (DFII10, resmi TIPS getirisi)",
            "seri_kod": "DFII10",
            "birim": "%",
            "seri": cikti_seriler["us10y_reel"]["seri"],
        }
        print(f"  ABD 10Y reel faiz: DFII10 (resmi) kullanildi, {len(cikti_seriler['us10y_reel']['seri'])} aylik gozlem")
    else:
        us10y_map = {s["tarih"]: s["deger"] for s in cikti_seriler.get("us10y", {}).get("seri", [])}
        breakeven_map = {s["tarih"]: s["deger"] for s in cikti_seriler.get("breakeven", {}).get("seri", [])}
        ortak_aylar = sorted(set(us10y_map) & set(breakeven_map), reverse=True)
        reel_faiz_seri = [{"tarih": ay, "deger": round(us10y_map[ay] - breakeven_map[ay], 3)} for ay in ortak_aylar]
        if reel_faiz_seri:
            cikti_seriler["us_reel_faiz"] = {
                "ad": "ABD 10Y Reel Faiz (YAKLASIK: DGS10 - Breakeven, DFII10 gelmedigi icin yedek yontem)",
                "seri_kod": "hesaplanmis: DGS10 - T10YIE",
                "birim": "%",
                "seri": reel_faiz_seri,
            }
            print(f"  ABD 10Y reel faiz (YEDEK yontem, DFII10 gelmedi): {len(reel_faiz_seri)} aylik gozlem")

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
    # Gercek ICE DXY denemesi (basarisizsa sessizce atlanir, FRED serisi kalir)
    try:
        dxy_seriyi_ekle(cikti_seriler)
    except Exception as e:
        print(f"DXY eklenemedi: {e}")

    HEDEF.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")
    print(f"\nTamamlandi -> {HEDEF}")
    if bos_olanlar:
        print(f"  UYARI: su seriler bos geldi: {', '.join(bos_olanlar)}")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# GERCEK DXY (ICE Dolar Endeksi) - Stooq denemesi          [29 Agu 2026]
# ---------------------------------------------------------------------------
# SORUN: Panel "Dolar Endeksi" diye FRED'in DTWEXBGS serisini gosteriyordu.
# Bu GERCEK DXY DEGIL - FED'in 26 para birimli genis endeksi, 2006=100 olcekli.
# Yani ~97 beklerken ~120 goruluyordu. Sayi yanlis degil, ETIKET yanlisti.
#
# COZUM: Once Stooq'tan gercek ICE DXY (^DX) denenir. Stooq ucretsiz, anahtar
# istemez ve CSV doner. BASARISIZ OLURSA sessizce eski FRED serisine dusulur
# ama etiket "FED genis endeksi" olarak kalir - yani panelde ASLA yanlis isim
# gorunmez.
#
# DIKKAT - DOGRULANMAMIS: Bu fonksiyon yazildigi ortamda dis ag kapali oldugu
# icin CALISTIRILARAK test EDILEMEDI. Ilk calismada loglara bakin:
#   "DXY: Stooq'tan alindi"  -> calisiyor
#   "DXY: Stooq basarisiz"   -> Stooq BIST/DXY vermiyor, FRED'e dusuldu
# Ikinci durumda alternatif: EVDS kurlarindan ICE formuluyle kendimiz hesaplariz.

STOOQ_DXY_URL = "https://stooq.com/q/d/l/?s=^dx&i=d"


def dxy_seriyi_ekle(seriler_cikti):
    """
    Ana akisa baglanti noktasi. main() icinde, FRED serileri yazildiktan
    HEMEN SONRA cagrilmalidir:
        dxy_seriyi_ekle(cikti["seriler"])
    Basarisizsa hicbir sey yapmaz - panel FRED genis endeksini gostermeye
    devam eder ve etiketi zaten dogrudur ("Dolar Endeksi (FED, genis)").
    """
    seri = gercek_dxy_dene()
    if not seri:
        return False
    # Aylik ortalamaya indirge (makro_gecmis.json aylik seri tutar)
    from collections import defaultdict
    aylik = defaultdict(list)
    for r in seri:
        aylik[r["tarih"][:7]].append(r["deger"])
    seriler_cikti["dxy_gercek"] = {
        "ad": "Dolar Endeksi (ICE DXY)",
        "seri_kod": "^DX (Stooq)",
        "birim": "endeks",
        "seri": [{"tarih": a, "deger": round(sum(v)/len(v), 2)} for a, v in sorted(aylik.items())],
    }
    return True


def gercek_dxy_dene(gun_sayisi=3650):
    """
    Stooq'tan gunluk ICE DXY serisi. Basarisizsa None doner - CAGIRAN TARAF
    None'i "veri yok" olarak ele almali, sifir veya tahmin URETMEMELI.
    """
    try:
        import csv
        import io
        import urllib.request
        istek = urllib.request.Request(
            STOOQ_DXY_URL, headers={"User-Agent": "Mozilla/5.0 (GNC Insight panel)"})
        with urllib.request.urlopen(istek, timeout=25) as y:
            metin = y.read().decode("utf-8", "replace")
        satirlar = list(csv.DictReader(io.StringIO(metin)))
        if not satirlar or "Close" not in satirlar[0]:
            print("DXY: Stooq beklenen formatta yanit vermedi")
            return None
        seri = []
        for r in satirlar[-gun_sayisi:]:
            try:
                seri.append({"tarih": r["Date"], "deger": float(r["Close"])})
            except (KeyError, ValueError):
                continue
        if len(seri) < 100:
            print(f"DXY: Stooq'tan sadece {len(seri)} kayit geldi, guvenilmez")
            return None
        son = seri[-1]["deger"]
        # Akil saglama testi: ICE DXY tarihsel olarak 70-130 bandinda hareket eder.
        # Bu bandin disindaki bir deger yanlis seriyi cektigimizi gosterir.
        if not (60 <= son <= 140):
            print(f"DXY: Stooq degeri bantta degil ({son}) - reddedildi")
            return None
        print(f"DXY: Stooq'tan alindi - {len(seri)} kayit, son deger {son}")
        return seri
    except Exception as e:
        print(f"DXY: Stooq basarisiz ({type(e).__name__}: {e}) - FRED genis endeksine dusuluyor")
        return None
