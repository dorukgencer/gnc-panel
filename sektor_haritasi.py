# -*- coding: utf-8 -*-
"""
GNC Insight - KANONİK SEKTÖR HARİTASI (örtüşen endeks düzeltmesi)

BULUNAN HATA (29 Ağu 2026):
  rotasyon_hesapla.py içinde şu not vardı:
     "Teknoloji sektorunun %37 gibi mantik disi bir agirlikla ciktigi tespit
      edildi, kok neden HENUZ KESIN degil"
  Kök neden bulundu ve burada çözülüyor.

  BIST endeksleri HER ZAMAN birbirinden ayrık değildir. Veride tam olarak bir
  kapsama ilişkisi var:

      XUTEK (Teknoloji, 42 hisse)  ⊃  XBLSM (Bilişim, 38 hisse)

  Yani Bilişim, Teknoloji'nin ALT endeksidir; 38 hisse ikisinde de listelenir.
  Eski kod hisse→sektör sözlüğünü kurarken "son gelen kazanır" davranışı
  gösteriyordu: 38 hisse XBLSM'e yazılıyor, XUTEK'te yalnızca 4 hisse kalıyordu.
  O 4 hissenin içinde ASELS gibi çok büyük bir şirket olduğu için XUTEK'in
  ağırlığı 4 hisseden hesaplanıp şişiyordu. Ayrıca aynı hisseler iki ayrı
  "sektör" olarak rotasyon grafiğinde iki kez temsil ediliyordu.

ÇÖZÜM: Kapsama ilişkileri VERİDEN otomatik tespit edilir. Bir endeks başka bir
endeksin tamamını içeriyorsa, ALT endeks sektör evreninden çıkarılır ve
hisseleri ÜST endekse atanır. Elle liste tutulmaz — yeni bir alt endeks
eklenirse kendiliğinden yakalanır.

Bu modülü sektör ağırlığı veya sektör ataması yapan HER script kullanmalıdır.
"""

import itertools
import json
from pathlib import Path

KLASOR = Path(__file__).parent
PANEL = KLASOR / "gnc-panel"


def ham_listeler():
    d = json.loads((PANEL / "sektor_hisseler.json").read_text(encoding="utf-8"))
    return {k: {h["kod"] for h in v} for k, v in d.get("hisseler", {}).items() if v}


def kapsamalari_bul(kume):
    """
    {ust_endeks: [alt_endeks, ...]} — A, B'nin TAMAMINI içeriyorsa A üsttür.
    Kısmi örtüşmeler burada YAKALANMAZ; onlar ayrı bir sorundur ve
    kanonik_harita() içinde ayrıca raporlanır.
    """
    ust = {}
    for a, b in itertools.permutations(kume, 2):
        if kume[b] and kume[b] <= kume[a] and len(kume[a]) > len(kume[b]):
            ust.setdefault(a, []).append(b)
    return ust


def kanonik_harita(sessiz=False):
    """
    Döner: (kod_to_sektor, sektor_kumeleri, rapor)
      kod_to_sektor    : {HISSE: SEKTOR}  — her hisse TEK sektörde
      sektor_kumeleri  : {SEKTOR: {hisseler}} — alt endeksler çıkarılmış
      rapor            : ne yapıldığının kaydı (panelde gösterilebilir)
    """
    kume = ham_listeler()
    ust = kapsamalari_bul(kume)
    alt_endeksler = {b for bs in ust.values() for b in bs}

    # Kısmi örtüşme kontrolü — kapsama değil ama kesişim varsa bu AYRI bir
    # sorundur ve otomatik çözülemez; raporlanır.
    kismi = []
    for a, b in itertools.combinations(sorted(kume), 2):
        k = kume[a] & kume[b]
        if k and not (kume[a] <= kume[b] or kume[b] <= kume[a]):
            kismi.append({"a": a, "b": b, "kesisim": len(k)})

    sektor_kumeleri = {k: v for k, v in kume.items() if k not in alt_endeksler}
    kod_to_sektor = {}
    cakisan = []
    for sek, hisseler in sektor_kumeleri.items():
        for h in hisseler:
            if h in kod_to_sektor and kod_to_sektor[h] != sek:
                cakisan.append({"kod": h, "a": kod_to_sektor[h], "b": sek})
            kod_to_sektor[h] = sek

    rapor = {
        "ham_endeks_sayisi": len(kume),
        "kanonik_sektor_sayisi": len(sektor_kumeleri),
        "cikarilan_alt_endeksler": [
            {"alt": b, "ust": a, "alt_hisse": len(kume[b]), "ust_hisse": len(kume[a])}
            for a, bs in ust.items() for b in bs
        ],
        "kismi_ortusmeler": kismi,
        "coklu_atama_kalanlari": cakisan,
        "tekil_hisse": len(kod_to_sektor),
    }

    if not sessiz:
        for c in rapor["cikarilan_alt_endeksler"]:
            print(f"  [SEKTOR] {c['alt']} ({c['alt_hisse']} hisse), "
                  f"{c['ust']} ({c['ust_hisse']}) endeksinin ALT KUMESI -> "
                  f"sektor evreninden cikarildi, hisseler {c['ust']}'e atandi")
        if kismi:
            print(f"  [SEKTOR][UYARI] {len(kismi)} KISMI ortusme var, otomatik "
                  f"cozulemez: {kismi[:3]}")
        if cakisan:
            print(f"  [SEKTOR][UYARI] {len(cakisan)} hisse hala birden fazla "
                  f"sektorde: {cakisan[:3]}")

    return kod_to_sektor, sektor_kumeleri, rapor


def sektor_agirliklari(alan="hao_pd"):
    """
    Kanonik haritayla sektör ağırlığı. Çifte sayım YOK.
    Döner: (agirlik_yuzde, rapor)
    """
    kod_to_sektor, _, rapor = kanonik_harita(sessiz=True)
    hv = json.loads((PANEL / "sektor_hisse_veri.json").read_text(encoding="utf-8"))["hisseler"]
    toplam, sayi, genel = {}, {}, 0.0
    for kod, v in hv.items():
        if not isinstance(v, dict):
            continue
        d = v.get(alan) or v.get("pd")
        s = kod_to_sektor.get(kod)
        if d and s:
            toplam[s] = toplam.get(s, 0.0) + d
            sayi[s] = sayi.get(s, 0) + 1
            genel += d
    agirlik = {s: round(v / genel * 100, 2) for s, v in toplam.items()} if genel else {}
    rapor["kapsanan_hisse"] = sum(sayi.values())
    rapor["beklenen_hisse"] = len(kod_to_sektor)
    rapor["kapsam_orani"] = round(rapor["kapsanan_hisse"] / max(1, len(kod_to_sektor)) * 100, 1)
    rapor["hisse_sayilari"] = sayi
    # Az hisseden gelen buyuk agirlik supheli - eski kodun uyarisi korunuyor
    rapor["supheli"] = [s for s, a in agirlik.items() if a > 20 and sayi.get(s, 0) < 5]
    return agirlik, rapor


if __name__ == "__main__":
    print("KANONIK SEKTOR HARITASI")
    kod_to_sektor, kumeler, rapor = kanonik_harita()
    print(f"\n  ham endeks: {rapor['ham_endeks_sayisi']} -> kanonik sektor: "
          f"{rapor['kanonik_sektor_sayisi']}")
    print(f"  tekil hisse: {rapor['tekil_hisse']}")
    a, r = sektor_agirliklari()
    print(f"\n  kapsam: {r['kapsanan_hisse']}/{r['beklenen_hisse']} (%{r['kapsam_orani']})")
    print("\n  AGIRLIKLAR:")
    for s, v in sorted(a.items(), key=lambda x: -x[1]):
        print(f"    {s:<8} %{v:>5.1f}   {r['hisse_sayilari'].get(s, 0):>3} hisse")
    if r["supheli"]:
        print(f"\n  [UYARI] az hisseden gelen buyuk agirlik: {r['supheli']}")
