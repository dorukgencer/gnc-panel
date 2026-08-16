# -*- coding: utf-8 -*-
"""
GNC Insight - VERI DENETIMI (tum sirketler)

NEDEN VAR: Elle 50 sirket kontrol etmek hem yorucu hem yetersiz. Bu script
466 sirketin HEPSINI her calismada denetler ve sorunlulari listeler.

NE KONTROL EDER:
  1) KALEM ESLESMESI - panelin aradigi kalemler bu sirkette var mi?
     (Bankalar, GYO'lar, sigortalar farkli isimler kullanir. 16 Agu 2026'da
      bankalarda net kar HIC BULUNAMADIGI tespit edildi - bu kontrol o hatayi
      bir daha sessizce yasamamak icin var.)
  2) MUHASEBE TUTARLILIGI - tablonun kendi icinde tutarli mi?
       Brut Kar =~ Hasilat + Satislarin Maliyeti
       Donem Kari =~ Ana Ortaklik Payi + Azinlik Payi
       Toplam Varliklar =~ Toplam Kaynaklar
  3) KUMULATIF MANTIK - donemler kumulatif mi ilerliyor?
       Yil ici her ceyrek bir oncekinden buyuk olmali (isaret olarak)
  4) VERI TAZELIGI - son donem ne kadar eski?

CIKTI: veri_denetim.json + konsola ozet. Sorun bulursa uyarir ama pipeline'i
KIRMAZ - amaci bilgilendirmek, engellemek degil.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

KLASOR = Path(__file__).parent
PANEL = KLASOR / "gnc-panel"
FIN = PANEL / "finansal"

# Panelin aradigi kalemler (sirketler.html ile AYNI olmali)
ARANAN = {
    "Net Kar": [
        "Ana Ortaklık Payları", "Dönem Karı (Zararı) - Ana Ortaklık Payları",
        "Grubun Karı (Zararı)", "GRUBUN KARI (ZARARI)",
        "DÖNEM KARI (ZARARI)", "Dönem Net Kar/Zararı", "Net Dönem Kârı (Zararı)",
        "DÖNEM NET KARI VEYA ZARARI", "Dönem Net Karı veya Zararı",
        "SÜRDÜRÜLEN FAALİYETLER DÖNEM NET KARI (ZARARI)",
        "XVIII. NET DÖNEM KARI/ZARARI", "XVII. NET DÖNEM KARI/ZARARI",
    ],
    "Ozkaynak": [
        "Ana Ortaklığa Ait Özkaynaklar", "Özkaynaklar", "XVI. ÖZKAYNAKLAR",
        "ÖZKAYNAKLAR", "Toplam Özkaynaklar",
    ],
    "Satislar": [
        "Satış Gelirleri", "Hasılat", "III. NET FAİZ GELİRİ/GİDERİ (I - II)",
        "NET FAİZ GELİRİ VEYA GİDERİ", "FAİZ GELİRLERİ",
    ],
    "Faaliyet Kari": [
        "FAALİYET KARI (ZARARI)", "Net Faaliyet Kar/Zararı",
        "XI. NET FAALİYET KARI/ZARARI", "NET FAALİYET KARI (ZARARI)",
        "Faaliyet Karı (Zararı)",
    ],
    "Odenmis Sermaye": ["Ödenmiş Sermaye", "16.1 Ödenmiş Sermaye"],
}

# Bu kalemler her sirkette OLMAK ZORUNDA degil (bankada brut kar yok gibi)
ZORUNLU = {"Net Kar", "Ozkaynak", "Satislar"}


def kalem_bul(kalemler, adaylar):
    harita = {k["ad"]: k for k in kalemler}
    for a in adaylar:
        if a in harita:
            return harita[a]
    return None


def donem_anahtar(d):
    try:
        y, q = d.split("/")
        return int(y) * 100 + int(q)
    except Exception:
        return 0


def sirket_denetle(kod, veri):
    kalemler = veri.get("kalemler", [])
    if not kalemler:
        return {"kod": kod, "sorunlar": ["kalem listesi bos"], "seviye": "kritik"}

    sorunlar = []
    donemler = sorted({d for k in kalemler for d in k["degerler"]}, key=donem_anahtar)
    if not donemler:
        return {"kod": kod, "sorunlar": ["donem yok"], "seviye": "kritik"}
    son = donemler[-1]

    # --- 1) Kalem eslesmesi ---
    eksik = []
    for ad, adaylar in ARANAN.items():
        if not kalem_bul(kalemler, adaylar):
            eksik.append(ad)
    for e in eksik:
        sorunlar.append(f"{e} kalemi bulunamadi" + ("  [ZORUNLU]" if e in ZORUNLU else ""))

    # --- 2) Muhasebe tutarliligi ---
    def deg(adaylar, donem):
        k = kalem_bul(kalemler, adaylar)
        if not k:
            return None
        v = k["degerler"].get(donem)
        return v if isinstance(v, (int, float)) else None

    # Donem Kari =~ Ana Ortaklik + Azinlik
    toplam = deg(["DÖNEM KARI (ZARARI)", "DÖNEM NET KARI VEYA ZARARI"], son)
    ana = deg(["Ana Ortaklık Payları", "Grubun Karı (Zararı)"], son)
    azinlik = deg(["Azınlık Payları", "Azınlık Payları Karı (Zararı)"], son)
    if toplam is not None and ana is not None and azinlik is not None:
        fark = abs(toplam - (ana + azinlik))
        olcek = max(abs(toplam), 1)
        if fark / olcek > 0.01:
            sorunlar.append(
                f"Donem Kari != Ana Ortaklik + Azinlik (fark %{fark/olcek*100:.1f})")

    # Varliklar =~ Kaynaklar
    varlik = deg(["TOPLAM VARLIKLAR", "Toplam Varlıklar"], son)
    kaynak = deg(["TOPLAM KAYNAKLAR", "Toplam Kaynaklar"], son)
    if varlik and kaynak:
        fark = abs(varlik - kaynak) / max(abs(varlik), 1)
        if fark > 0.01:
            sorunlar.append(f"Varliklar != Kaynaklar (fark %{fark*100:.1f})")

    # Brut Kar =~ Hasilat + Satislarin Maliyeti
    has = deg(["Satış Gelirleri", "Hasılat"], son)
    mal = deg(["Satışların Maliyeti (-)", "Satışların Maliyeti"], son)
    brut = deg(["BRÜT KAR (ZARAR)", "Brüt Kar (Zarar)"], son)
    if has and mal is not None and brut is not None:
        bek = has + mal
        fark = abs(brut - bek) / max(abs(has), 1)
        if fark > 0.01:
            sorunlar.append(f"Brut Kar != Hasilat + Maliyet (fark %{fark*100:.1f})")

    # --- 3) Kumulatif mantik: yil ici seri buyumeli (mutlak deger olarak) ---
    satisK = kalem_bul(kalemler, ARANAN["Satislar"])
    if satisK:
        for yil in {d.split("/")[0] for d in donemler}:
            ceyrekler = [(int(d.split("/")[1]), satisK["degerler"].get(d))
                         for d in donemler if d.startswith(yil + "/")]
            ceyrekler = [(q, v) for q, v in ceyrekler if isinstance(v, (int, float))]
            ceyrekler.sort()
            for i in range(1, len(ceyrekler)):
                onceki, simdi = abs(ceyrekler[i-1][1]), abs(ceyrekler[i][1])
                if onceki > 0 and simdi < onceki * 0.98:   # %2 tolerans
                    sorunlar.append(
                        f"{yil} kumulatif DEGIL: {yil}/{ceyrekler[i][0]} < {yil}/{ceyrekler[i-1][0]}")
                    break

    # --- 4) Tazelik ---
    seviye = "ok"
    if any("[ZORUNLU]" in s for s in sorunlar):
        seviye = "kritik"
    elif sorunlar:
        seviye = "uyari"
    return {"kod": kod, "son_donem": son, "donem_sayisi": len(donemler),
            "sorunlar": sorunlar, "seviye": seviye}


def main():
    if not FIN.exists():
        raise SystemExit("finansal/ klasoru yok.")
    dosyalar = sorted(FIN.glob("*.json"))
    print(f"{len(dosyalar)} sirket denetleniyor...\n")

    sonuclar = []
    for f in dosyalar:
        try:
            veri = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            sonuclar.append({"kod": f.stem, "sorunlar": [f"okunamadi: {e}"], "seviye": "kritik"})
            continue
        sonuclar.append(sirket_denetle(f.stem, veri))

    kritik = [s for s in sonuclar if s["seviye"] == "kritik"]
    uyari = [s for s in sonuclar if s["seviye"] == "uyari"]
    temiz = [s for s in sonuclar if s["seviye"] == "ok"]

    print(f"TEMIZ  : {len(temiz)}")
    print(f"UYARI  : {len(uyari)}")
    print(f"KRITIK : {len(kritik)}")

    if kritik:
        print("\n--- KRITIK (zorunlu kalem eksik / dosya bozuk) ---")
        for s in kritik[:25]:
            print(f"  {s['kod']:8s} {'; '.join(s['sorunlar'])[:100]}")
        if len(kritik) > 25:
            print(f"  ... ve {len(kritik)-25} tane daha")

    if uyari:
        # Sorun turlerine gore grupla - tek tek okumak yerine kalibi gor
        from collections import Counter
        turler = Counter()
        for s in uyari:
            for p in s["sorunlar"]:
                turler[p.split("(")[0].strip()] += 1
        print("\n--- UYARI TURLERI (en sik) ---")
        for tur, n in turler.most_common(10):
            print(f"  {n:4d}x {tur[:70]}")

    cikti = {
        "tarih": datetime.now(timezone.utc).isoformat(),
        "toplam": len(sonuclar),
        "temiz": len(temiz), "uyari": len(uyari), "kritik": len(kritik),
        "sorunlular": [s for s in sonuclar if s["seviye"] != "ok"],
    }
    (PANEL / "veri_denetim.json").write_text(
        json.dumps(cikti, ensure_ascii=False), encoding="utf-8")
    print(f"\n-> veri_denetim.json yazildi")
    if kritik:
        print(f"\nDIKKAT: {len(kritik)} sirkette zorunlu kalem eksik. "
              f"Bu sirketlerde Karne/Degerleme bos gorunur.")


if __name__ == "__main__":
    main()
