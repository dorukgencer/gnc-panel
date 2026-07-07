# -*- coding: utf-8 -*-
"""
GNC Insight - Sektor-Hisse Eslemesi Cekici (borsapy / Is Yatirim)
Her BIST sektor endeksinin GERCEK tam uye listesini cekip
gnc-panel/sektor_hisseler.json'a yazar. Elle hazirlanan BIST 100 listesinin
yerini alir. Uyeler ceyrekte bir degistigi icin ayda bir calisir.
"""

import json
from datetime import datetime
from pathlib import Path

import borsapy as bp

SEKTORLER = [
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


def main():
    hisseler = {}
    toplam = 0
    for kod, ad in SEKTORLER:
        try:
            comp = bp.Index(kod).components
            liste = []
            for c in (comp or []):
                s = (c.get("symbol") or "").strip()
                n = (c.get("name") or "").strip()
                if s:
                    liste.append({"kod": s, "ad": n or s})
            if liste:
                hisseler[kod] = liste
                toplam += len(liste)
                print(f"  {kod:6s} {len(liste)} hisse")
            else:
                print(f"  {kod:6s} bos")
        except Exception as e:
            print(f"  {kod:6s} hata: {e}")

    cikti = {
        "not": "Sektor endekslerinin gercek uye listesi. Otomatik (borsapy/Is Yatirim). Aylik guncellenir.",
        "guncelleme": datetime.now().isoformat(),
        "hisseler": hisseler,
    }
    hedef = Path(__file__).parent / "gnc-panel" / "sektor_hisseler.json"
    hedef.parent.mkdir(parents=True, exist_ok=True)
    hedef.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")
    print(f"\nTamamlandi: {len(hisseler)} sektor, {toplam} hisse -> {hedef}")


if __name__ == "__main__":
    main()
