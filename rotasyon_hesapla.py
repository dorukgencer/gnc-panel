# -*- coding: utf-8 -*-
"""
GNC Insight - Sektor Rotasyonu Hesaplayici (RRG-ilhamli, sadelestirilmis)
Girdiler: gnc-panel/endeks_gecmis/{KOD}.json (XU100 + 23 sektor, gunluk kapanis)
Cikti: gnc-panel/rotasyon_gecmis.json

ONEMLI - BU GERCEK/RESMI "RRG" (Relative Rotation Graph) FORMULU DEGIL.
Julius de Kempenaer'in orijinal JdK RS-Ratio/RS-Momentum formulu daha karmasik
bir istatistiksel yumusatma kullanir. Biz bunun SADELESTIRILMIS, seffaf,
kendi tanimladigimiz bir versiyonunu kullaniyoruz - GNC Insight'in kendi
metodolojisi olarak sunulmali, "resmi RRG" olarak degil.

Eksenler:
  X (13 haftalik goreli guc)  = sektorun 13 haftalik toplam getirisi
                                  - XU100'un 13 haftalik toplam getirisi
                                  (yuzde puan fark)
  Y (4 haftalik momentum)     = X(bugun) - X(4 hafta once)
                                  (farkin acilma/kapanma hizi)

Evre siniflandirmasi:
  X>0 ve Y>0  -> Genisleme   (BIST100'u geciyor, fark aciliyor)
  X<=0 ve Y>0 -> Toparlanma  (geride ama fark kapaniyor)
  X>0 ve Y<=0 -> Yavaslama   (hala geciyor ama fark kapanmaya basladi)
  X<=0 ve Y<=0-> Daralma     (geride ve fark aciliyor)

Trail (iz): Ayni X,Y hesaplamasi ~12 hafta (3 ay) once icin de yapilir,
boylece "3 ay onceki konumdan simdiki konuma" ok cizilebilir.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

KLASOR = Path(__file__).parent
ENDEKS_KLASOR = KLASOR / "gnc-panel" / "endeks_gecmis"
HEDEF = KLASOR / "gnc-panel" / "rotasyon_gecmis.json"

X_PENCERE_HAFTA = 13   # goreli guc penceresi (~3 ay)
Y_PENCERE_HAFTA = 4    # momentum penceresi
TRAIL_GERI_HAFTA = 12  # iz'in basladigi nokta (~3 ay once)

# Grafik geometrisi (sartnamedeki SVG koordinat sistemiyle birebir)
MERKEZ_X, MERKEZ_Y = 300, 300
MAX_YARICAP = 240  # 260'in biraz altinda, kenara yapismasin diye pay birakildi
OLCEK_TAVANI = 15.0  # +-15 puanlik fark, maks yaricapa denk gelsin (normalize icin)


def sektor_listesi():
    dosyalar = [d for d in ENDEKS_KLASOR.glob("*.json") if d.stem != "XU100"]
    return [d.stem for d in dosyalar]


def seriyi_yukle(kod):
    yol = ENDEKS_KLASOR / f"{kod}.json"
    if not yol.exists():
        return None
    veri = json.loads(yol.read_text(encoding="utf-8"))
    seri = veri.get("seri", [])
    # tarihe gore artan sirala (eskiden yeniye), hizli index erisimi icin
    seri = sorted(seri, key=lambda s: s["tarih"])
    return seri, veri.get("ad", kod)


def haftalik_kapanis(seri):
    """Gunluk seriyi haftalik (her haftanin SON islem gunu) kapanisa indirger."""
    haftalik = {}
    for s in seri:
        try:
            hafta_no = datetime.strptime(s["tarih"], "%Y-%m-%d").isocalendar()[:2]  # (yil, hafta)
        except Exception:
            continue
        haftalik[hafta_no] = s["kapanis"]  # ayni haftada en son gorulen deger kalir (seri artan sirali oldugu icin)
    # sirali liste haline getir
    return [{"hafta": h, "kapanis": v} for h, v in sorted(haftalik.items())]


def getiri(haftalik, i, pencere):
    """haftalik[i] ile haftalik[i-pencere] arasindaki toplam getiri (%)."""
    if i - pencere < 0 or i >= len(haftalik):
        return None
    simdi = haftalik[i]["kapanis"]
    eski = haftalik[i - pencere]["kapanis"]
    if not eski:
        return None
    return (simdi / eski - 1) * 100


def x_serisi_hesapla(sek_haftalik, xu_haftalik):
    """Her hafta indeksi icin X(t) = sektor_13hf_getiri(t) - xu100_13hf_getiri(t)."""
    n = min(len(sek_haftalik), len(xu_haftalik))
    x_serisi = []
    for i in range(n):
        sek_g = getiri(sek_haftalik, i, X_PENCERE_HAFTA)
        xu_g = getiri(xu_haftalik, i, X_PENCERE_HAFTA)
        if sek_g is None or xu_g is None:
            x_serisi.append(None)
        else:
            x_serisi.append(sek_g - xu_g)
    return x_serisi


def evre_belirle(x, y):
    if x > 0 and y > 0:
        return "genisleme"
    if x <= 0 and y > 0:
        return "toparlanma"
    if x > 0 and y <= 0:
        return "yavaslama"
    return "daralma"


def koordinat_hesapla(x, y):
    """X,Y puan farkini dogru ceyrege ve merkeze gore piksel konumuna cevirir."""
    x_olcekli = max(-1.0, min(1.0, x / OLCEK_TAVANI)) * MAX_YARICAP
    y_olcekli = max(-1.0, min(1.0, y / OLCEK_TAVANI)) * MAX_YARICAP
    # SVG'de y asagi dogru artar; Y ekseni "momentum yukari = grafikte yukari"
    # olmasi icin isaretini ters ceviriyoruz (matematiksel yukari = kucuk SVG y).
    cx = MERKEZ_X + x_olcekli
    cy = MERKEZ_Y - y_olcekli
    return round(cx, 1), round(cy, 1)


def bubble_yaricap(weight):
    import math
    if weight is None or weight <= 0:
        weight = 0.1
    return round(7 + math.sqrt(weight) * 2.9, 1)


def sektor_agirliklari():
    """sektor_verisi.json'dan (varsa) guncel agirliklari oku. Yoksa None doner,
    o zaman bubble boyutu esit varsayilir (agirlik netlesince duzelir)."""
    try:
        veri = json.loads((KLASOR / "gnc-panel" / "sektor_verisi.json").read_text(encoding="utf-8"))
        return {e["kod"]: e.get("agirlik") for e in veri.get("endeksler", []) if e.get("tip") == "sektor"}
    except Exception:
        return {}


def main():
    xu_ham = seriyi_yukle("XU100")
    if not xu_ham:
        raise SystemExit("XU100 endeks_gecmis dosyasi bulunamadi. Once endeks_gecmis_cek.py calismis olmali.")
    xu_seri, _ = xu_ham
    xu_haftalik = haftalik_kapanis(xu_seri)

    kodlar = sektor_listesi()
    if not kodlar:
        raise SystemExit("Hicbir sektor endeks_gecmis dosyasi bulunamadi.")

    agirliklar = sektor_agirliklari()
    sonuc = []
    atlanan = []

    for kod in kodlar:
        yuklenen = seriyi_yukle(kod)
        if not yuklenen:
            atlanan.append(kod)
            continue
        sek_seri, sek_ad = yuklenen
        sek_haftalik = haftalik_kapanis(sek_seri)
        if len(sek_haftalik) < X_PENCERE_HAFTA + Y_PENCERE_HAFTA + TRAIL_GERI_HAFTA + 2:
            atlanan.append(kod)
            continue

        x_serisi = x_serisi_hesapla(sek_haftalik, xu_haftalik)
        son_i = len(x_serisi) - 1

        x_simdi = x_serisi[son_i]
        x_4hf_once = x_serisi[son_i - Y_PENCERE_HAFTA] if son_i - Y_PENCERE_HAFTA >= 0 else None
        if x_simdi is None or x_4hf_once is None:
            atlanan.append(kod)
            continue
        y_simdi = x_simdi - x_4hf_once

        trail_i = son_i - TRAIL_GERI_HAFTA
        if trail_i - Y_PENCERE_HAFTA >= 0 and x_serisi[trail_i] is not None and x_serisi[trail_i - Y_PENCERE_HAFTA] is not None:
            x_trail = x_serisi[trail_i]
            y_trail = x_serisi[trail_i] - x_serisi[trail_i - Y_PENCERE_HAFTA]
            cx_trail, cy_trail = koordinat_hesapla(x_trail, y_trail)
        else:
            cx_trail, cy_trail = None, None

        cx, cy = koordinat_hesapla(x_simdi, y_simdi)
        evre = evre_belirle(x_simdi, y_simdi)
        agirlik = agirliklar.get(kod)

        sonuc.append({
            "kod": kod,
            "ad": sek_ad,
            "evre": evre,
            "x_goreli_guc_13hf": round(x_simdi, 2),
            "y_momentum_4hf": round(y_simdi, 2),
            "cx": cx, "cy": cy,
            "cx_3ay_once": cx_trail, "cy_3ay_once": cy_trail,
            "yaricap": bubble_yaricap(agirlik),
            "agirlik": agirlik,
        })

    if not sonuc:
        raise SystemExit("Hicbir sektor icin rotasyon hesaplanamadi (yetersiz gecmis veri).")

    cikti = {
        "guncelleme": datetime.now(timezone.utc).isoformat(),
        "not": (
            "GNC Insight'in kendi sadelestirilmis rotasyon metodolojisi - "
            "resmi/akademik RRG (Relative Rotation Graph) formulu degildir. "
            f"X ekseni: {X_PENCERE_HAFTA} haftalik goreli guc (XU100'e gore yuzde puan fark). "
            f"Y ekseni: bu farkin son {Y_PENCERE_HAFTA} haftadaki degisimi (momentum). "
            "Egitim ve arastirma amaclidir, yatirim tavsiyesi degildir."
        ),
        "parametreler": {"x_pencere_hafta": X_PENCERE_HAFTA, "y_pencere_hafta": Y_PENCERE_HAFTA, "trail_geri_hafta": TRAIL_GERI_HAFTA},
        "sektorler": sonuc,
    }
    HEDEF.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")

    print(f"Tamamlandi: {len(sonuc)} sektor -> {HEDEF}")
    if atlanan:
        print(f"  Atlanan ({len(atlanan)}): {', '.join(atlanan)} (yetersiz gecmis veri)")
    for s in sorted(sonuc, key=lambda x: x["x_goreli_guc_13hf"], reverse=True)[:5]:
        print(f"  {s['kod']:6s} {s['evre']:12s} X={s['x_goreli_guc_13hf']:+.1f}  Y={s['y_momentum_4hf']:+.1f}")


if __name__ == "__main__":
    main()
