# -*- coding: utf-8 -*-
"""
GNC Insight - Sirketler Sayfasi Veri Hazirlayici

Iki cikti uretir:
  1. gnc-panel/sirket_listesi.json  -> liste sayfasi icin (kod, ad, sektor, g1/h1/a1, fiyat)
  2. gnc-panel/tufe_ceyreklik.json  -> ceyrek sonu TUFE endeksi (enflasyon duzeltmesi icin)

HICBIR YENI VERI CEKMEZ - mevcut dosyalardan turetir, saniyeler icinde biter.

TUFE NEDEN CEYREKLIK: Karne grafikleri ceyreklik. Bir ceyregin rakamini BUGUNE
tasimak icin o ceyrek sonundaki TUFE endeksi ile bugunku endeksin oranini
kullaniyoruz (Finvest/yatirim101'in "Enflasyon duzeltmesi" dugmesi de ayni
mantikla calisiyor - 15 Agu 2026'da HEKTS ekran goruntusuyle dogrulandi:
2023Q4 satislari dugme acikken ~2 kat buyuyor, 2026Q2 neredeyse ayni kaliyor).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

KLASOR = Path(__file__).parent
PANEL = KLASOR / "gnc-panel"


def yukle(dosya):
    try:
        return json.loads((PANEL / dosya).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  {dosya} okunamadi: {e}")
        return None


def tufe_ceyreklik_uret():
    """deflator.json'daki AYLIK TUFE endeksinden CEYREK SONU (3,6,9,12)
    degerlerini cikarir -> {"2016/3": 412.3, ..., "2026/6": 3120.5}"""
    veri = yukle("deflator.json")
    if not veri:
        return {}
    seri = veri.get("deflatorler", {}).get("tufe", {}).get("seri", [])
    if not seri:
        print("  UYARI: deflator.json icinde TUFE serisi bulunamadi")
        return {}

    ceyrekler = {}
    en_son_ay = None
    en_son_deger = None
    for nokta in seri:
        tarih = nokta.get("tarih", "")   # "YYYY-MM"
        deger = nokta.get("deger")
        if deger is None or "-" not in tarih:
            continue
        yil, ay = tarih.split("-")[0], tarih.split("-")[1]
        if en_son_ay is None or tarih > en_son_ay:
            en_son_ay, en_son_deger = tarih, deger
        if ay in ("03", "06", "09", "12"):
            ceyrekler[f"{yil}/{int(ay)}"] = deger

    # BUGUNKU (en son aciklanan) endeks - tasima islemi buna gore yapilir.
    # Ceyrek sonu olmasa bile en son ay kullanilir (orn. Agustos verisi varsa o).
    if en_son_deger:
        ceyrekler["_guncel"] = en_son_deger
        ceyrekler["_guncel_ay"] = en_son_ay
    return ceyrekler


def sirket_listesi_uret():
    """Liste sayfasi icin: her hissenin kodu, sektoru, gunluk/haftalik/aylik
    getirisi ve guncel fiyati."""
    hisse_veri = yukle("sektor_hisse_veri.json")
    sektor_harita_ham = yukle("sektor_hisseler.json")
    sektor_verisi = yukle("sektor_verisi.json")
    if not hisse_veri or not sektor_harita_ham:
        return []

    # kod -> sektor_kod  ve  kod -> sirket adi (varsa)
    kod_sektor, kod_ad = {}, {}
    for sektor_kod, hisseler in sektor_harita_ham.get("hisseler", {}).items():
        for h in hisseler:
            kod = h.get("kod")
            if not kod:
                continue
            kod_sektor[kod] = sektor_kod
            # Bazi kaynaklarda sirket adi da olabilir - varsa kullan, yoksa kod
            if h.get("ad"):
                kod_ad[kod] = h["ad"]

    # sektor_kod -> sektor adi
    sektor_ad = {}
    if sektor_verisi:
        for e in sektor_verisi.get("endeksler", []):
            if e.get("tip") == "sektor":
                sektor_ad[e["kod"]] = e.get("ad", e["kod"])

    liste = []
    for kod, v in hisse_veri.get("hisseler", {}).items():
        if not isinstance(v, dict):
            continue
        sektor_kod = kod_sektor.get(kod)
        liste.append({
            "kod": kod,
            "ad": kod_ad.get(kod, kod),   # sirket adi yoksa kod gosterilir
            "sektor": sektor_kod,
            "sektor_ad": sektor_ad.get(sektor_kod, sektor_kod or "-"),
            "fiyat": v.get("fiyat"),
            "g1": v.get("g1"),
            "h1": v.get("h1"),
            "a1": v.get("a1"),
        })
    liste.sort(key=lambda x: x["kod"])
    return liste


def main():
    print("Ceyreklik TUFE endeksi hazirlaniyor...")
    tufe = tufe_ceyreklik_uret()
    ceyrek_sayisi = len([k for k in tufe if not k.startswith("_")])
    print(f"  {ceyrek_sayisi} ceyrek endeksi (guncel: {tufe.get('_guncel_ay', '-')})")

    print("Sirket listesi hazirlaniyor...")
    liste = sirket_listesi_uret()
    print(f"  {len(liste)} sirket")
    if liste:
        adli = sum(1 for s in liste if s["ad"] != s["kod"])
        print(f"  {adli} sirketin tam adi var, {len(liste)-adli} tanesi sadece kod gosterecek")

    if not liste and not tufe:
        raise SystemExit("Ne sirket listesi ne TUFE uretilemedi - girdi dosyalari eksik.")

    now = datetime.now(timezone.utc).isoformat()

    (PANEL / "sirket_listesi.json").write_text(
        json.dumps({"guncelleme": now, "sirketler": liste}, ensure_ascii=False), encoding="utf-8")
    (PANEL / "tufe_ceyreklik.json").write_text(
        json.dumps({"guncelleme": now, "endeksler": tufe}, ensure_ascii=False), encoding="utf-8")

    print(f"\nTamamlandi -> sirket_listesi.json, tufe_ceyreklik.json")


if __name__ == "__main__":
    main()
