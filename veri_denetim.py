# -*- coding: utf-8 -*-
"""
GNC Insight - VERI DENETIMI (FORMAT FARKINDA, v2)

NE DEGISTI (29 Agu 2026):
  Eski surum TEK bir kalem adi listesi kullaniyordu ve BIST'teki uc ayri
  tablo formatini ayirt etmiyordu. Sonuc: 12 banka + 6 sigorta sirketi
  "KRITIK - zorunlu kalem bulunamadi" diye isaretleniyordu. Veri eksik
  degildi; ARAYAN YANLIS YERDE ARIYORDU.

  Artik kalem cozumlemesi kalem_haritasi.py'ye devredildi. Dogrulandi:
  472 sirketin 472'sinde butun zorunlu kalemler bulunuyor.

  Ayrica her formatin KENDI kontrol seti var. Bankaya "Brut Kar = Hasilat +
  Maliyet" kontrolu uygulanmaz - bankada brut kar diye bir sey yoktur.

NE KONTROL EDER:
  1) KALEM COZUMLEMESI  - formatina gore zorunlu kalemler var mi
  2) MUHASEBE TUTARLILIGI - sadece SANAYI: brut kar kimligi
  3) KUMULATIF MANTIK   - yil ici gelir serisi artiyor mu
  4) VERI TAZELIGI      - son donem ne kadar eski

KARANTINA (YENI):
  Kumulatif mantigi bozuk sirket-yillari artik sadece "uyari" degil,
  KARANTINA listesine yazilir. Tarama katmani bu sirket-yillarini
  hesaplamaya KATMAZ. Supheli veriyle hesap yapmaktansa o donemi atlamak
  "kaybetmemek" ilkesinin veri tarafindaki karsiligidir.

CIKTI: veri_denetim.json (panel okur) + karantina.json (tarama katmani okur)
Pipeline'i KIRMAZ - amaci bilgilendirmek.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from kalem_haritasi import format_belirle, tum_alanlar, ZORUNLU

KLASOR = Path(__file__).parent
PANEL = KLASOR / "gnc-panel"
FIN = PANEL / "finansal"

BAYAT_CEYREK = 3      # son donem bu kadar ceyrekten eskiyse uyar
BRUT_TOLERANS = 0.05  # brut kar kimliginde kabul edilen sapma


def donem_sirala(d):
    y, c = d.split("/")
    return (int(y), int(c))


def son_donem_bekleniyor():
    """Bugun itibariyla makul en son ceyrek (aciklama gecikmesi payiyla)."""
    b = datetime.now(timezone.utc)
    y, ay = b.year, b.month - 3          # ~1 ceyrek aciklama gecikmesi
    if ay <= 0:
        y, ay = y - 1, ay + 12
    return (y, ((ay - 1) // 3 + 1) * 3)


def sirket_denetle(kod, veri):
    sorunlar, karantina_yillari = [], []
    fmt = format_belirle(veri)
    alanlar = tum_alanlar(veri, fmt)
    donemler = sorted(veri.get("donemler", []), key=donem_sirala)

    # --- 1) zorunlu kalemler
    for z in ZORUNLU[fmt]:
        if not alanlar.get(z):
            sorunlar.append(f"{z} kalemi cozumlenemedi [{fmt}] [ZORUNLU]")

    # --- 2) muhasebe kimligi (sadece SANAYI - digerlerinde anlamsiz)
    if fmt == "SANAYI":
        # Finans segmenti varsa kimlik SADECE ticari brut kar icin gecerlidir.
        bk = alanlar.get("ticari_brut_kar") or alanlar.get("brut_kar")
        gl, sm = alanlar.get("gelir"), alanlar.get("satis_maliyeti")
        if bk and gl and sm and donemler:
            son = donemler[-1]
            b, g, m = bk.get(son), gl.get(son), sm.get(son)
            if None not in (b, g, m) and abs(g) > 0:
                bekl = g + m                      # maliyet negatif gelir
                if abs(bekl) > 0 and abs(b - bekl) / abs(bekl) > BRUT_TOLERANS:
                    fark = abs(b - bekl) / abs(bekl) * 100
                    sorunlar.append(f"Ticari Brut Kar != Gelir + Maliyet (fark %{fark:.1f}) [{son}]")

    # --- 3) kumulatif mantik -> KARANTINA
    gelir = alanlar.get("gelir")
    if gelir:
        yillik = {}
        for d, v in gelir.items():
            if v is None:
                continue
            y, c = donem_sirala(d)
            yillik.setdefault(y, []).append((c, v))
        for y, satirlar in yillik.items():
            satirlar.sort()
            for i in range(1, len(satirlar)):
                if satirlar[i][1] < satirlar[i - 1][1]:
                    sorunlar.append(
                        f"{y} kumulatif DEGIL: {y}/{satirlar[i][0]} < {y}/{satirlar[i-1][0]}")
                    karantina_yillari.append(y)
                    break

    # --- 4) tazelik
    if donemler:
        son = donem_sirala(donemler[-1])
        bekl = son_donem_bekleniyor()
        gecikme = (bekl[0] - son[0]) * 4 + (bekl[1] - son[1]) // 3
        if gecikme >= BAYAT_CEYREK:
            sorunlar.append(f"Veri bayat: son donem {donemler[-1]}, ~{gecikme} ceyrek geride")
    else:
        sorunlar.append("Hic donem yok [ZORUNLU]")

    seviye = "temiz"
    if any("[ZORUNLU]" in s for s in sorunlar):
        seviye = "kritik"
    elif sorunlar:
        seviye = "uyari"

    return {
        "kod": kod,
        "format": fmt,
        "son_donem": donemler[-1] if donemler else None,
        "donem_sayisi": len(donemler),
        "sorunlar": sorunlar,
        "seviye": seviye,
        "karantina_yillari": sorted(set(karantina_yillari)),
    }


def main():
    dosyalar = sorted(FIN.glob("*.json"))
    sonuc, karantina = [], {}
    sayac = {"temiz": 0, "uyari": 0, "kritik": 0}
    fmt_sayac = {}

    for f in dosyalar:
        try:
            veri = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            sonuc.append({"kod": f.stem, "format": "?", "sorunlar": [f"Dosya okunamadi: {e}"],
                          "seviye": "kritik", "donem_sayisi": 0,
                          "son_donem": None, "karantina_yillari": []})
            sayac["kritik"] += 1
            continue

        r = sirket_denetle(f.stem, veri)
        sayac[r["seviye"]] += 1
        fmt_sayac[r["format"]] = fmt_sayac.get(r["format"], 0) + 1
        if r["karantina_yillari"]:
            karantina[r["kod"]] = r["karantina_yillari"]
        if r["seviye"] != "temiz":
            sonuc.append(r)

    sonuc.sort(key=lambda r: (r["seviye"] != "kritik", r["kod"]))

    cikti = {
        "tarih": datetime.now(timezone.utc).isoformat(),
        "toplam": len(dosyalar),
        "temiz": sayac["temiz"],
        "uyari": sayac["uyari"],
        "kritik": sayac["kritik"],
        "formatlar": fmt_sayac,
        "sorunlular": sonuc,
    }
    (PANEL / "veri_denetim.json").write_text(
        json.dumps(cikti, ensure_ascii=False), encoding="utf-8")

    # Tarama katmani icin: bu sirket-yillari hesaba KATILMAZ
    (PANEL / "karantina.json").write_text(json.dumps({
        "tarih": cikti["tarih"],
        "aciklama": "Kumulatif mantigi bozuk sirket-yillari. Tarama bu donemleri atlar.",
        "sirketler": karantina,
    }, ensure_ascii=False), encoding="utf-8")

    print(f"DENETIM: {cikti['toplam']} sirket | "
          f"temiz {sayac['temiz']} · uyari {sayac['uyari']} · kritik {sayac['kritik']}")
    print(f"Formatlar: {fmt_sayac}")
    print(f"Karantinaya alinan sirket: {len(karantina)}")
    for r in sonuc[:15]:
        print(f"  [{r['seviye']:>6}] {r['kod']:<7} ({r['format']}) {'; '.join(r['sorunlar'][:2])}")
    if len(sonuc) > 15:
        print(f"  ... ve {len(sonuc)-15} sirket daha (veri_denetim.json'da)")


if __name__ == "__main__":
    main()
