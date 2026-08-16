# -*- coding: utf-8 -*-
"""
GNC Insight - KAP Sirket Kimlikleri

SORUN: KAP'in sirket sayfasi URL'i hisse koduyla DEGIL, dahili bir kimlikle
calisiyor:
    https://www.kap.org.tr/tr/sirket-bilgileri/ozet/4028e4a140ee35c00140ee5d194a0055
                                                    ^^^^ HEKTS'in KAP kimligi
Bu kimlik hicbir yerde hisse koduyla eslenmis halde bulunmuyor.

COZUM: KAP'in BIST sirketleri listesinden kod -> kimlik eslemesini bir kez
cikarip JSON'a yaziyoruz. Sayfa bu JSON'u kullanip dogrudan link veriyor.

DIKKAT: KAP'in sayfa yapisi degisirse bu script sessizce bos donebilir.
O yuzden:
  - Bulunan kimlik sayisini logluyoruz (birden fazla calismada dususe gecerse
    yapinin degistigini anlariz)
  - Basarisiz olursa MEVCUT dosyayi BOZMUYORUZ, sadece kimlik alani bos kalir
  - Panel, kimlik yoksa bagimsiz bir kaynaga (Fintables) yonlendirir
Yani bu script calismasa bile panel dogrulama linkini kaybetmez.
"""

import json
import re
import time
from pathlib import Path

import requests

KLASOR = Path(__file__).parent
PANEL = KLASOR / "gnc-panel"
KAP_LISTE = "https://www.kap.org.tr/tr/bist-sirketler"
BASLIK = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept-Language": "tr-TR,tr;q=0.9",
}


def kap_sayfasi_al(deneme_sayisi=3):
    """KAP listesini ceker. Basarisiz olursa None doner - pipeline kirilmaz."""
    for deneme in range(deneme_sayisi):
        try:
            y = requests.get(KAP_LISTE, headers=BASLIK, timeout=30)
            if y.status_code == 200 and len(y.text) > 5000:
                return y.text
            print(f"  deneme {deneme+1}: HTTP {y.status_code}, {len(y.text)} bayt")
        except Exception as e:
            print(f"  deneme {deneme+1} hata: {str(e)[:90]}")
        if deneme < deneme_sayisi - 1:
            time.sleep(5 * (deneme + 1))
    return None


def kimlikleri_ayikla(html):
    """kod -> kap_kimlik esleme sozlugu.

    KAP'in liste sayfasinda her satirda hem sirket ozet linki hem hisse kodu
    bulunur. Iki farkli desen deniyoruz cunku KAP zaman zaman isaretlemeyi
    degistiriyor; ikisi de tutmazsa bos doner ve mevcut veri korunur."""
    esleme = {}

    # Desen 1: link ve kod ayni blokta, link once
    for m in re.finditer(
        r'sirket-bilgileri/ozet/([0-9a-fA-F]{32})[\s\S]{0,600}?'
        r'>\s*([A-Z]{3,6})(?:,\s*[A-Z]{3,6})*\s*<', html):
        kimlik, kod = m.group(1), m.group(2)
        esleme.setdefault(kod, kimlik)

    # Desen 2: kod once, link sonra
    if len(esleme) < 100:
        for m in re.finditer(
            r'>\s*([A-Z]{3,6})\s*<[\s\S]{0,600}?sirket-bilgileri/ozet/([0-9a-fA-F]{32})', html):
            kod, kimlik = m.group(1), m.group(2)
            esleme.setdefault(kod, kimlik)

    return esleme


def main():
    dosya = PANEL / "sirket_listesi.json"
    if not dosya.exists():
        raise SystemExit("sirket_listesi.json yok - once sirket_listesi_hazirla.py calismali.")

    veri = json.loads(dosya.read_text(encoding="utf-8"))
    sirketler = veri.get("sirketler", [])
    onceki = sum(1 for s in sirketler if s.get("kap"))

    print("KAP BIST sirketler listesi cekiliyor...")
    html = kap_sayfasi_al()
    if not html:
        print("KAP'a erisilemedi. Mevcut kimlikler KORUNUYOR, dosya degistirilmedi.")
        print(f"  (dosyada zaten {onceki} kimlik var)")
        return

    esleme = kimlikleri_ayikla(html)
    print(f"  {len(esleme)} kod-kimlik eslesmesi bulundu")

    if len(esleme) < 100:
        print("UYARI: Beklenenden COK AZ eslesme cikti - KAP sayfa yapisi degismis olabilir.")
        print("       Mevcut kimlikler KORUNUYOR, dosya degistirilmedi.")
        return

    yeni, guncel = 0, 0
    for s in sirketler:
        k = esleme.get(s["kod"])
        if not k:
            continue
        if s.get("kap") != k:
            if s.get("kap"):
                guncel += 1
            else:
                yeni += 1
            s["kap"] = k

    eslesen = sum(1 for s in sirketler if s.get("kap"))
    dosya.write_text(json.dumps(veri, ensure_ascii=False), encoding="utf-8")
    print(f"\nTamamlandi: {eslesen}/{len(sirketler)} sirkete KAP kimligi eklendi "
          f"({yeni} yeni, {guncel} guncellendi)")
    eksik = [s["kod"] for s in sirketler if not s.get("kap")]
    if eksik:
        ornek = ", ".join(eksik[:12]) + ("..." if len(eksik) > 12 else "")
        print(f"  {len(eksik)} sirket eslenemedi (panelde Fintables linki gosterilecek): {ornek}")


if __name__ == "__main__":
    main()
