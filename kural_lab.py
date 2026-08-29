# -*- coding: utf-8 -*-
"""
GNC Insight - KURAL LABORATUVARI (çalıştırıcı)

Ne yapar: ölçüm panelini bir kez kurar, sonra istenen bütün kural
kombinasyonlarını geçmişe dönük test eder ve tek bir JSON'a yazar.

ÇALIŞMA BİÇİMLERİ
  python kural_lab.py                  → varsayılan: referans setler + 2..5 kural taraması
  python kural_lab.py --k 3            → sadece 3 süzgeçli kombinasyonlar
  python kural_lab.py --k 2 3 4 6      → istenen kural sayıları
  python kural_lab.py --hizli          → daha az kombinasyon (deneme için)

AŞIRI UYDURMAYA KARŞI ÜÇ KORUMA
  1. Her kombinasyon YIL YIL raporlanır. En kötü yılı eksi olan kombinasyon,
     ortalaması ne olursa olsun işaretlenir.
  2. Her kombinasyon REJİM bazında raporlanır. Tek bir rejimde parlayıp
     diğerlerinde çöken kombinasyon işaretlenir.
  3. Kontrol grubu (hiç kural yok) her zaman listede kalır. Onu geçemeyen
     kombinasyon, kural eklemenin zarar verdiği anlamına gelir.

CIKTI: gnc-panel/kural_lab.json
"""

import argparse
import itertools
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

import gecmis_test as GT
import kural_motoru as KM

PANEL = Path(__file__).parent / "gnc-panel"

# Taramada kullanılacak süzgeç havuzu. Hepsi bağımsız ve tek boyutlu.
HAVUZ = ["nakit_akisi", "faiz_karsilama", "borcluluk", "tahakkuk",
         "ucuzluk", "ma_ustu", "momentum_pozitif", "buyume_pozitif", "kar_pozitif"]

# Elle tanımlanmış referans setler — "bunlarla başlayalım" dediklerimiz
REFERANSLAR = [
    {"ad": "Kontrol (kural yok)", "suzgecler": [], "siralama": "buyuk", "koruma": "yok"},
    {"ad": "2 kural — sağlamlık", "suzgecler": ["nakit_akisi", "faiz_karsilama"],
     "siralama": "ucuz", "koruma": "yok"},
    {"ad": "3 kural — sağlamlık + ucuzluk", "suzgecler": ["nakit_akisi", "faiz_karsilama", "borcluluk"],
     "siralama": "ucuz", "koruma": "yok"},
    {"ad": "4 kural — sistem çekirdeği", "suzgecler": ["nakit_akisi", "faiz_karsilama", "borcluluk", "tahakkuk"],
     "siralama": "ucuz", "koruma": "yok"},
    {"ad": "4 kural + zamanlama", "suzgecler": ["nakit_akisi", "faiz_karsilama", "borcluluk", "ma_ustu"],
     "siralama": "ucuz", "koruma": "yok"},
    {"ad": "6 kural — tam set", "suzgecler": ["nakit_akisi", "faiz_karsilama", "borcluluk",
                                              "tahakkuk", "ucuzluk", "ma_ustu"],
     "siralama": "ucuz", "koruma": "yok"},
    {"ad": "4 kural + nakde geçme", "suzgecler": ["nakit_akisi", "faiz_karsilama", "borcluluk", "tahakkuk"],
     "siralama": "ucuz", "koruma": "endeks_ma"},
    {"ad": "6 kural + nakde geçme", "suzgecler": ["nakit_akisi", "faiz_karsilama", "borcluluk",
                                                  "tahakkuk", "ucuzluk", "ma_ustu"],
     "siralama": "ucuz", "koruma": "endeks_ma"},
]


def isaretler(sonuc, rejim_getiri, kontrol_yillik):
    """Aşırı uydurma ve kırılganlık işaretleri. Sayı değil, UYARI üretir."""
    u = []
    yillik = [y.get("getiri") for y in sonuc["alt_donemler"]["yillik"] if y.get("getiri") is not None]
    if yillik and min(yillik) < 0:
        u.append(f"en kötü yıl %{min(yillik):.0f}")
    if len(yillik) >= 3:
        sirali = sorted(yillik, reverse=True)
        if sirali[0] > sum(sirali[1:]) * 1.5:
            u.append("getirinin çoğu tek yıldan")
    rj = [v.get("yillik_getiri") for v in rejim_getiri.values()
          if v.get("yillik_getiri") is not None and v.get("yaklasik_ay", 0) >= 4]
    if rj and min(rj) < 0:
        u.append("bir rejimde negatif")
    if kontrol_yillik is not None and sonuc["olcut"].get("yillik_getiri", 0) < kontrol_yillik:
        u.append("kontrol grubunun altında")
    if sonuc["islem_sayisi"] > 600:
        u.append("çok yüksek devir")
    return u


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", nargs="*", type=int, default=[2, 3, 4, 5],
                    help="Taranacak süzgeç sayıları")
    ap.add_argument("--hizli", action="store_true", help="Havuzu daralt, hızlı çalış")
    ap.add_argument("--siralama", default="ucuz", help="Taramada kullanılacak sıralama")
    args = ap.parse_args()

    havuz = HAVUZ[:6] if args.hizli else HAVUZ

    print("Panel kuruluyor (ölçümler BİR KEZ hesaplanır)...")
    t0 = time.time()
    veri = GT.veri_yukle()
    kararlar, panel, gunler, fiyat, xu_ma, xu = KM.panel_kur(veri)
    print(f"  {len(kararlar)} karar günü, panel {time.time()-t0:.1f} sn'de kuruldu")

    rejimler = KM.rejim_serisi()

    # --- referans setler
    sonuclar = []
    print("\nREFERANS SETLER")
    for r in REFERANSLAR:
        s = KM.kombinasyon_calistir(kararlar, panel, gunler, fiyat, xu_ma,
                                    r["suzgecler"], r["siralama"], r["koruma"])
        s["ad"] = r["ad"]
        s["tip"] = "referans"
        s["rejim"] = KM.rejim_bazinda_getiri(s["seri"], rejimler)
        sonuclar.append(s)
        o = s["olcut"]
        print(f"  {r['ad']:<28} yıllık %{o.get('yillik_getiri',0):>6.1f}  "
              f"düşüş %{o.get('max_dusus',0):>6.1f}  nakit {s['nakit_ay']:>2} ay  "
              f"işlem {s['islem_sayisi']:>4}")

    kontrol = next((s for s in sonuclar if s["ad"].startswith("Kontrol")), None)
    kontrol_yillik = kontrol["olcut"].get("yillik_getiri") if kontrol else None

    # --- kombinasyon taraması
    print(f"\nKOMBINASYON TARAMASI  havuz={len(havuz)} süzgeç, k={args.k}")
    toplam = sum(len(list(itertools.combinations(havuz, k))) for k in args.k)
    print(f"  {toplam} kombinasyon × 2 koruma = {toplam*2} test")
    t1, n = time.time(), 0
    for k in args.k:
        for kombo in itertools.combinations(havuz, k):
            for koruma in ("yok", "endeks_ma"):
                s = KM.kombinasyon_calistir(kararlar, panel, gunler, fiyat, xu_ma,
                                            list(kombo), args.siralama, koruma)
                s["ad"] = " + ".join(kombo) + ("  [nakit korumalı]" if koruma != "yok" else "")
                s["tip"] = "tarama"
                s["rejim"] = KM.rejim_bazinda_getiri(s["seri"], rejimler)
                sonuclar.append(s)
                n += 1
        print(f"  k={k} bitti ({n}/{toplam*2}, {time.time()-t1:.0f} sn)")

    # --- ETKİSİZ KURAL TESPİTİ
    # Bir kural eklendiğinde sonuç HİÇ değişmiyorsa o kural, o bağlamda
    # etkisizdir. Örnek: FD/FAVÖK net borcu zaten paya dahil ettiği için
    # borçluluk süzgeci "ucuz" sıralamasıyla birlikte hiçbir şey değiştirmez.
    # Etkisiz kuralı sistemde tutmak, olmayan bir korumaya güvenmektir.
    imza = {}
    for s in sonuclar:
        h = tuple(round(r["deger"], 2) for r in s["seri"])
        imza.setdefault(h, []).append(s)
    for grup in imza.values():
        if len(grup) < 2:
            continue
        enaz = min(grup, key=lambda x: len(x["suzgecler"]))
        for s in grup:
            fazla = [k for k in s["suzgecler"] if k not in enaz["suzgecler"]]
            if fazla:
                s["etkisiz_kurallar"] = fazla
                s["esdeger"] = enaz["ad"]

    for s in sonuclar:
        s.setdefault("etkisiz_kurallar", [])
        s["uyarilar"] = isaretler(s, s["rejim"], kontrol_yillik)
        if s["etkisiz_kurallar"]:
            s["uyarilar"].append("etkisiz kural: " + ", ".join(s["etkisiz_kurallar"]))


    # --- en iyiler: SADECE getiriye gore degil
    def puan(s):
        o = s["olcut"]
        y, d = o.get("yillik_getiri", 0), abs(o.get("max_dusus", 1) or 1)
        return (y / d) - len(s["uyarilar"]) * 0.15      # uyari basina ceza
    sirali = sorted([s for s in sonuclar if s["tip"] == "tarama"], key=puan, reverse=True)

    # DOSYA BOYUTU: 900+ kombinasyonun tam serisi ~7 MB eder ve sayfayi bogar.
    # Grafikte gosterilecekler (referanslar + en iyi 25) tam seriyi korur,
    # digerleri sadece OLCUT tasir. Kullanici birini secerse laboratuvari
    # o kombinasyonla yeniden calistirabilir.
    # DUZELTME: once sadece "en iyi 25"e tam seri veriliyordu, digerlerinin
    # grafigi BOS ciziliyordu - kullanicinin sectigi kombinasyon cogu zaman o
    # 25'in disinda oluyor ve grafik hic gorunmuyordu. Artik HERKESE aylik
    # cozunurlukte seri veriliyor (250px'lik grafik icin fazlasiyla yeterli),
    # one cikanlara daha sik ornekleme.
    onemli = {id(s) for s in sirali[:25]}
    onemli |= {id(s) for s in sonuclar if s["tip"] == "referans"}
    for s in sonuclar:
        tam = s["seri"]
        if not tam:
            s["seri_var"] = False
            continue
        if id(s) in onemli:
            adim = max(1, len(tam) // 220)
        else:
            # ay sonu benzeri: ~62 nokta
            adim = max(1, len(tam) // 62)
        s["seri"] = tam[::adim]
        if s["seri"][-1] is not tam[-1]:
            s["seri"].append(tam[-1])
        s["seri_var"] = True

    print(f"\nEN İYİ 10 (getiri/düşüş oranına göre, uyarı cezalı)")
    print(f"{'kombinasyon':<58}{'yıllık':>8}{'düşüş':>8}{'uyarı':>7}")
    for s in sirali[:10]:
        o = s["olcut"]
        print(f"  {s['ad'][:56]:<56}{o.get('yillik_getiri',0):>7.1f}%{o.get('max_dusus',0):>7.1f}%"
              f"{len(s['uyarilar']):>7}")

    cikti = {
        "tarih": datetime.now(timezone.utc).isoformat(),
        "baslangic": GT.BASLANGIC.isoformat(), "bitis": GT.BITIS.isoformat(),
        "karar_sayisi": len(kararlar),
        "pozisyon": 10, "sektor_tavani": 3,
        "islem_maliyeti_tek_yon": GT.ISLEM_MALIYETI,
        "suzgec_katalogu": {k: {"ad": v[0], "aciklama": v[1]} for k, v in KM.SUZGECLER.items()},
        "siralama_katalogu": {k: {"ad": v[0]} for k, v in KM.SIRALAMALAR.items()},
        "koruma_katalogu": {k: {"ad": v[0], "aciklama": v[1]} for k, v in KM.KORUMALAR.items()},
        "rejim_adlari": KM.REJIM_ADI,
        "rejim_serisi": {a: v for a, v in rejimler.items()
                         if GT.BASLANGIC.isoformat()[:7] <= a <= GT.BITIS.isoformat()[:7]},
        "benchmark": _benchmark(xu, sonuclar[0]["seri"], rejimler),
        "sonuclar": sonuclar,
        "uyari": ("Yüzlerce kombinasyon deneyip en iyisini seçmek, veriye uydurmanın "
                  "kendisidir. Buradaki sıralama bir KEŞİF aracıdır, seçim gerekçesi "
                  "değildir. Bir kombinasyonu ancak MANTIĞI savunulabiliyorsa ve tüm "
                  "rejimlerde ayakta kalıyorsa ciddiye alın."),
    }
    (PANEL / "kural_lab.json").write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")
    print(f"\n-> gnc-panel/kural_lab.json  ({len(sonuclar)} sonuç, "
          f"{(PANEL/'kural_lab.json').stat().st_size/1e6:.1f} MB)")


def _benchmark(xu, ornek_seri, rejimler):
    seri, ilk = [], None
    for r in ornek_seri:
        v = xu.get(r["tarih"])
        if v is None:
            continue
        if ilk is None:
            ilk = v
        seri.append({"tarih": r["tarih"], "deger": round(GT.BASLANGIC_SERMAYE * v / ilk, 2)})
    return {"ad": "BIST 100", "seri": seri, "olcut": GT.olcut(seri),
            "alt_donemler": GT.alt_donemler(seri),
            "rejim": KM.rejim_bazinda_getiri(seri, rejimler)}


if __name__ == "__main__":
    main()
