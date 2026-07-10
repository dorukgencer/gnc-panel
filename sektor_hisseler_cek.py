# -*- coding: utf-8 -*-
"""
GNC Insight - Sektor-Hisse Eslemesi Cekici (borsapy / Is Yatirim) - DAYANIKLI
Her BIST sektor endeksinin GERCEK tam uye listesini cekip
gnc-panel/sektor_hisseler.json'a yazar. Uyeler ceyrekte bir degistigi icin ayda bir calisir.

DAYANIKLILIK:
- XUTEK (Teknoloji/savunma) eklendi -> ASELS gibi hisseler artik geliyor.
- Her sektor retry ile cekilir; timeout olursa o sektor icin ELDEKI ESKI uye listesi korunur.
- HER_ZAMAN_DAHIL: kritik hisseler bir endeksten hic gelmese bile garanti eklenir.
- Hic taze sektor gelmezse mevcut dosyaya dokunulmaz.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import borsapy as bp

SEKTORLER = [
    ("XUTEK", "Teknoloji"),
    ("XBANK", "Bankacilik"), ("XSGRT", "Sigorta"), ("XFINK", "Fin. Kiralama Faktoring"),
    ("XHOLD", "Holding ve Yatirim"), ("XGYO", "Gayrimenkul Yat. Ort."),
    ("XYORT", "Menkul Kiymet Yat. Ort."), ("XGIDA", "Gida ve Icecek"),
    ("XKMYA", "Kimya Petrol Plastik"), ("XMANA", "Metal Ana Sanayi"),
    ("XMESY", "Metal Esya Makina"), ("XTAST", "Tas Toprak (Cam Cimento)"),
    ("XTEKS", "Tekstil ve Deri"), ("XKAGT", "Orman Kagit Basim"),
    ("XELKT", "Elektrik"), ("XILTM", "Iletisim"), ("XULAS", "Ulastirma"),
    ("XTCRT", "Ticaret"), ("XTRZM", "Turizm"), ("XINSA", "Insaat ve Bayindirlik"),
    ("XMADN", "Madencilik"), ("XBLSM", "Bilisim"), ("XSPOR", "Spor"),
]

# Bir endeksten gelmese bile garanti dahil edilecek kritik hisseler.
# {sektor_kodu: [(hisse_kodu, hisse_adi), ...]}
HER_ZAMAN_DAHIL = {
    "XUTEK": [("ASELS", "Aselsan"), ("KAREL", "Karel Elektronik"), ("LOGO", "Logo Yazilim"),
              ("NETAS", "Netas Telekom"), ("ARDYZ", "ARD Grup"), ("SMART", "Smart Gunes"),
              ("PENTA", "Penta Teknoloji"), ("KFEIN", "Kafein Yazilim"), ("ALCTL", "Alcatel Lucent"),
              ("INDES", "Indeks Bilgisayar"), ("DGATE", "Datagate"), ("ESCOM", "Escort Teknoloji")],
}

DENEME = 3
BEKLE = 2


def sektor_cek(kod):
    """Bir sektorun uyelerini retry ile ceker; basarisizsa None."""
    for i in range(DENEME):
        try:
            comp = bp.Index(kod).components
            liste = []
            for c in (comp or []):
                s = (c.get("symbol") or "").strip()
                n = (c.get("name") or "").strip()
                if s:
                    liste.append({"kod": s, "ad": n or s})
            if liste:
                return liste
        except Exception as e:
            print(f"  {kod:6s} deneme {i+1}/{DENEME} hata: {str(e)[:60]}")
        if i < DENEME - 1:
            time.sleep(BEKLE)
    return None


def eski_yukle(hedef):
    if hedef.exists():
        try:
            data = json.loads(hedef.read_text(encoding="utf-8"))
            return data.get("hisseler", {}) or {}
        except Exception as e:
            print(f"Eski dosya okunamadi: {e}")
    return {}


def main():
    hedef = Path(__file__).parent / "gnc-panel" / "sektor_hisseler.json"
    hedef.parent.mkdir(parents=True, exist_ok=True)
    eski = eski_yukle(hedef)

    hisseler = {}
    taze_sayi = 0

    for kod, ad in SEKTORLER:
        liste = sektor_cek(kod)
        if liste:
            hisseler[kod] = liste
            taze_sayi += 1
            print(f"  {kod:6s} {len(liste)} hisse (taze)")
        elif kod in eski and eski[kod]:
            hisseler[kod] = eski[kod]
            print(f"  {kod:6s} taze gelmedi -> eski liste korundu ({len(eski[kod])})")
        else:
            print(f"  {kod:6s} veri yok")

    # Guvenlik listesi: garanti dahil edilecek hisseleri ekle (varsa duplike etme)
    for kod, ekstra in HER_ZAMAN_DAHIL.items():
        mevcut = hisseler.get(kod, [])
        varolan = {h["kod"] for h in mevcut}
        for hk, hn in ekstra:
            if hk not in varolan:
                mevcut.append({"kod": hk, "ad": hn})
                varolan.add(hk)
        if mevcut:
            hisseler[kod] = mevcut

    if taze_sayi == 0 and not eski:
        print("\nHic veri yok; dosya yazilmadi.")
        return

    toplam = sum(len(v) for v in hisseler.values())
    cikti = {
        "not": "Sektor endekslerinin uye listesi (borsapy/Is Yatirim) + guvenlik listesi. Aylik guncellenir.",
        "guncelleme": datetime.now(timezone.utc).isoformat(),
        "hisseler": hisseler,
    }
    hedef.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")
    print(f"\nTamamlandi: {len(hisseler)} sektor, {toplam} hisse -> {hedef}")


if __name__ == "__main__":
    main()
