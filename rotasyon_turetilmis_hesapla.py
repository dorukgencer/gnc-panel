# -*- coding: utf-8 -*-
"""
GNC Insight - Turetilmis Rotasyon Metrikleri (Endekse Katki + Isi Haritasi)

AMAC 1 - GUVENLIK: Bu hesaplar ONCEDEN tarayiciya inen JS icinde yapiliyordu,
yani metodoloji herkese acikti (sag tik -> kaynagi goruntule). Artik SUNUCUDA
(private repo) hesaplaniyor, tarayiciya sadece SONUC iniyor.

AMAC 2 - CEYREKLIK ISI HARITASI: yillik getirinin yani sira ceyreklik de
hesaplanir (Doruk'un istegi - ileride "gelecek modelleme" icin de kullanilacak).

Girdi:  sektor_verisi.json (getiriler), rotasyon_gecmis.json (agirliklar),
        sektor_gecmis.json (aylik getiri gecmisi)
Cikti:  gnc-panel/rotasyon_turetilmis.json

HICBIR YENI VERI CEKMEZ - mevcut dosyalardan turetir.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

KLASOR = Path(__file__).parent
PANEL = KLASOR / "gnc-panel"
HEDEF = PANEL / "rotasyon_turetilmis.json"


def yukle(dosya):
    try:
        return json.loads((PANEL / dosya).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  {dosya} okunamadi: {e}")
        return None


def endekse_katki_hesapla():
    """Katki = (agirlik / 100) * getiri  -- her periyot (g1/h1/a1) icin ayri.
    Agirlik rotasyon_gecmis.json'dan (gercek/HAO_PD duzeltmeli),
    getiri sektor_verisi.json'dan gelir."""
    sektor_verisi = yukle("sektor_verisi.json")
    rotasyon = yukle("rotasyon_gecmis.json")
    if not sektor_verisi or not rotasyon:
        return {}, False

    agirlik_harita = {s["kod"]: s.get("agirlik") for s in rotasyon.get("sektorler", [])}
    yaklasik_mi = bool(rotasyon.get("agirlik_yaklasik_mi"))

    sonuc = {}
    for e in sektor_verisi.get("endeksler", []):
        if e.get("tip") != "sektor":
            continue
        kod = e["kod"]
        agirlik = agirlik_harita.get(kod)
        if agirlik is None:
            continue
        girdi = {"ad": e.get("ad"), "agirlik": agirlik}
        for periyot in ("g1", "h1", "a1"):
            getiri = e.get(periyot)
            if getiri is not None:
                girdi[f"katki_{periyot}"] = round((agirlik / 100.0) * getiri, 4)
        if len(girdi) > 2:  # en az bir periyot hesaplanabildi
            sonuc[kod] = girdi
    return sonuc, yaklasik_mi


def _bilesik(getiriler):
    """Aylik yuzde getirileri BILESIK olarak toplam getiriye cevirir.
    (1+g1/100) * (1+g2/100) * ... - 1, yuzde olarak."""
    carpim = 1.0
    for g in getiriler:
        carpim *= (1 + (g or 0) / 100.0)
    return round((carpim - 1) * 100, 2)


def isi_haritasi_hesapla():
    """sektor_gecmis.json'daki aylik getirilerden hem YILLIK hem CEYREKLIK
    bilesik getiri tablosu uretir."""
    isi = yukle("sektor_gecmis.json")
    if not isi or "sektorler" not in isi:
        return {}, [], []

    yillik = {}
    ceyreklik = {}
    tum_yillar = set()
    tum_ceyrekler = set()

    for kod, veri in isi.get("sektorler", {}).items():
        aylik = veri.get("aylik", []) if isinstance(veri, dict) else []
        if not aylik:
            continue
        ad = veri.get("ad", kod) if isinstance(veri, dict) else kod

        # yil -> [getiriler],  "2025-Q3" -> [getiriler]
        yil_kova = {}
        ceyrek_kova = {}
        for a in aylik:
            ay_str = a.get("ay")  # "YYYY-MM"
            getiri = a.get("getiri")
            if not ay_str or getiri is None or "-" not in ay_str:
                continue
            yil, ay_no = ay_str.split("-")[0], ay_str.split("-")[1]
            try:
                ceyrek_no = (int(ay_no) - 1) // 3 + 1
            except ValueError:
                continue
            yil_kova.setdefault(yil, []).append(getiri)
            ceyrek_anahtar = f"{yil}-Q{ceyrek_no}"
            ceyrek_kova.setdefault(ceyrek_anahtar, []).append(getiri)

        yillik[kod] = {"ad": ad, "getiriler": {y: _bilesik(g) for y, g in yil_kova.items()}}
        ceyreklik[kod] = {"ad": ad, "getiriler": {c: _bilesik(g) for c, g in ceyrek_kova.items()}}
        tum_yillar.update(yil_kova.keys())
        tum_ceyrekler.update(ceyrek_kova.keys())

    return (
        {"yillik": yillik, "ceyreklik": ceyreklik},
        sorted(tum_yillar),
        sorted(tum_ceyrekler),
    )


def gecmis_yil_tutarlilik_kontrolu(yeni_isi, eski_hedef_yolu):
    """GUVENLIK (19 Tem 2026 - Doruk'un fark ettigi anormallik: Fin. Kiralama
    Faktoring'in 2026 (devam eden yil) bileşik getirisi birkaç gun icinde
    ~%460'tan ~%300'e degisti. Bu, ICINDE BULUNULAN yil icin bir olcude
    beklenebilir (yeni ay verisi eklendikce degisir), AMA TAMAMLANMIS
    (gecmis) yillarin ayni sekilde degismesi GERCEK bir veri/hesap hatasi
    olurdu - o yillar donmus olmali. Bu fonksiyon TAMAMLANMIS yillari
    (icinde bulunulan yil HARIC) onceki calismayla karsilastirir, fark
    varsa GURULTULU uyarir - boylece boyle bir anormallik sessizce
    birikmez, Actions log'unda hemen gorulur."""
    try:
        eski = json.loads(eski_hedef_yolu.read_text(encoding="utf-8"))
    except Exception:
        return  # ilk calistirma ya da eski dosya okunamiyor - karsilastirma yapilamaz, sorun degil

    eski_yillik = eski.get("isi_haritasi", {}).get("yillik", {})
    if not eski_yillik:
        return

    bu_yil = str(datetime.now(timezone.utc).year)
    TOLERANS_PUAN = 3.0  # yuzde puan - yuvarlama farkindan buyuk, gercek degisimden kucuk bir esik
    uyari_sayisi = 0

    for kod, eski_veri in eski_yillik.items():
        yeni_veri = yeni_isi.get("yillik", {}).get(kod, {})
        eski_getiriler = eski_veri.get("getiriler", {})
        yeni_getiriler = yeni_veri.get("getiriler", {})
        for yil, eski_deger in eski_getiriler.items():
            if yil == bu_yil:
                continue  # devam eden yil icin degisim BEKLENEN/NORMAL, atla
            yeni_deger = yeni_getiriler.get(yil)
            if yeni_deger is None or eski_deger is None:
                continue
            if abs(yeni_deger - eski_deger) > TOLERANS_PUAN:
                print(f"  [CIDDI UYARI] {kod} ({eski_veri.get('ad', kod)}) - {yil} yili TAMAMLANMIS "
                      f"bir yil olmasina ragmen getirisi degisti: %{eski_deger} -> %{yeni_deger} "
                      f"(fark: {round(yeni_deger - eski_deger, 1)} puan). Gecmis yillar DONMUS olmali - "
                      f"bu, sektor_gecmis.json'un yanlis/eksik veriyle YENIDEN yazildigina isaret "
                      f"ediyor olabilir (orn. Is Yatirim kesintisi sirasinda kismi veri gelmis olabilir). "
                      f"ELLE kontrol et, sektor_gecmis_cek.py'nin son calismasini incele.")
                uyari_sayisi += 1

    if uyari_sayisi:
        print(f"  Toplam {uyari_sayisi} tamamlanmis yil-sektor kombinasyonunda beklenmedik degisim tespit edildi.")


def main():
    print("Endekse Katki hesaplaniyor...")
    katki, agirlik_yaklasik_mi = endekse_katki_hesapla()
    print(f"  {len(katki)} sektor icin katki hesaplandi" + (" (agirlik YAKLASIK)" if agirlik_yaklasik_mi else ""))

    print("Isi Haritasi (yillik + ceyreklik) hesaplaniyor...")
    isi, yillar, ceyrekler = isi_haritasi_hesapla()
    print(f"  {len(isi.get('yillik', {}))} sektor, {len(yillar)} yil, {len(ceyrekler)} ceyrek")

    if not katki and not isi:
        raise SystemExit("Ne katki ne isi haritasi hesaplanabildi - girdi dosyalari eksik olabilir.")

    print("Gecmis yillarin tutarliligi kontrol ediliyor (tamamlanmis yillar donmus mu)...")
    gecmis_yil_tutarlilik_kontrolu(isi, HEDEF)

    cikti = {
        "guncelleme": datetime.now(timezone.utc).isoformat(),
        "endekse_katki": katki,
        "agirlik_yaklasik_mi": agirlik_yaklasik_mi,
        "isi_haritasi": isi,
        "yillar": yillar,
        "ceyrekler": ceyrekler,
    }
    HEDEF.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")
    print(f"\nTamamlandi -> {HEDEF}")


if __name__ == "__main__":
    main()
