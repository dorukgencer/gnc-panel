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


def rank_olcekle(deger, ayni_isaretli_degerler):
    """deger'in AYNI ISARETLI (>0 veya <=0) diger degerler arasindaki BUYUKLUK
    SIRASINI (percentile rank) 0..MAX_YARICAP araligina esler.

    NEDEN: Ham puan farkini sabit bir tavana (orn. +-15 puan) bolup olceklersek,
    gercek veride farklar bu tavanin cok altinda kaldiginda (Turkiye piyasasinda
    13 haftalik goreli guc farklari genelde kucuk) TUM baloncuklar merkeze
    yapisir, etiketler kenara sabitlendigi icin de merkez-kenar arasinda uzun,
    birbirine karisan cizgiler olusur (ilk versiyonda yasanan sorun buydu).
    Sira-tabanli olcek, ham buyukluk ne olursa olsun baloncuklarin HER ZAMAN
    ceyregin tum alanina yayilmasini garanti eder - gorsel karisikligi kokten
    cozer. Bedeli: konum artik "mutlak puan" degil "diger sektorlere gore sira"
    anlamina gelir - bu, orijinal sartnamenin zaten izin verdigi bir yaklasimdir
    ("ceyrek icindeki tam konum yaklasik olabilir").
    """
    if len(ayni_isaretli_degerler) <= 1:
        return MAX_YARICAP * 0.5
    kucuklerin_sayisi = sum(1 for d in ayni_isaretli_degerler if abs(d) < abs(deger))
    yuzde = kucuklerin_sayisi / max(1, len(ayni_isaretli_degerler) - 1)
    return 20 + yuzde * (MAX_YARICAP - 20)  # 20px min mesafe, tam merkeze yapismasin


def koordinat_hesapla_rank(x, y, tum_x, tum_y):
    x_ayni_isaret = [v for v in tum_x if (v > 0) == (x > 0)]
    y_ayni_isaret = [v for v in tum_y if (v > 0) == (y > 0)]
    x_mesafe = rank_olcekle(x, x_ayni_isaret)
    y_mesafe = rank_olcekle(y, y_ayni_isaret)
    x_yon = 1 if x > 0 else -1
    y_yon = 1 if y > 0 else -1
    cx = MERKEZ_X + x_yon * x_mesafe
    # SVG'de y asagi dogru artar; "momentum yukari = grafikte yukari" olsun diye ters ceviriyoruz.
    cy = MERKEZ_Y - y_yon * y_mesafe
    return round(cx, 1), round(cy, 1)


def bubble_yaricap(weight):
    import math
    if weight is None or weight <= 0:
        weight = 0.1
    return round(7 + math.sqrt(weight) * 2.9, 1)


def sektor_agirliklari():
    """Agirlik icin 3 kademeli oncelik:
    1. sektor_verisi.json'da dogrudan bir 'agirlik' alani varsa (ileride eklenebilir) onu kullan.
    2. sektor_hisse_veri.json'daki 'hao_pd' (halka aciklik oranina gore DUZELTILMIS
       piyasa degeri, 12 Tem 2026'da PD'den gercekten farkli oldugu dogrulandi) alanindan
       sektor bazinda toplayip normalize eder - bu GERCEK agirliktir, yaklasik degil.
    3. hao_pd de yoksa, HAM 'pd' alanindan (duzeltmesiz) yaklasik hesaplar - SADECE bu
       kademede sonuc 'yaklasik' olarak isaretlenir.
    Donus: (agirlik_sozlugu, yaklasik_mi)"""
    try:
        veri = json.loads((KLASOR / "gnc-panel" / "sektor_verisi.json").read_text(encoding="utf-8"))
        gercek = {e["kod"]: e.get("agirlik") for e in veri.get("endeksler", []) if e.get("tip") == "sektor"}
    except Exception:
        gercek = {}

    if any(v is not None for v in gercek.values()):
        return gercek, False  # dogrudan gercek veri var

    try:
        hisse_veri = json.loads((KLASOR / "gnc-panel" / "sektor_hisse_veri.json").read_text(encoding="utf-8"))
        sektor_harita = json.loads((KLASOR / "gnc-panel" / "sektor_hisseler.json").read_text(encoding="utf-8"))
        kod_to_sektor = {}
        for sektor_kod, hisseler in sektor_harita.get("hisseler", {}).items():
            for h in hisseler:
                kod_to_sektor[h["kod"]] = sektor_kod

        # Once HAO_PD (gercek, halka aciklik duzeltmeli) dene
        for alan, yaklasik_mi in [("hao_pd", False), ("pd", True)]:
            sektor_toplam = {}
            genel_toplam = 0.0
            for kod, v in hisse_veri.get("hisseler", {}).items():
                deger = v.get(alan) if isinstance(v, dict) else None
                sektor = kod_to_sektor.get(kod)
                if deger and sektor:
                    sektor_toplam[sektor] = sektor_toplam.get(sektor, 0.0) + deger
                    genel_toplam += deger
            if genel_toplam:
                sonuc = {kod: round(toplam / genel_toplam * 100, 2) for kod, toplam in sektor_toplam.items()}
                return sonuc, yaklasik_mi

        return {}, False
    except Exception:
        return {}, False


def main():
    xu_ham = seriyi_yukle("XU100")
    if not xu_ham:
        raise SystemExit("XU100 endeks_gecmis dosyasi bulunamadi. Once endeks_gecmis_cek.py calismis olmali.")
    xu_seri, _ = xu_ham
    xu_haftalik = haftalik_kapanis(xu_seri)

    kodlar = sektor_listesi()
    if not kodlar:
        raise SystemExit("Hicbir sektor endeks_gecmis dosyasi bulunamadi.")

    agirliklar, agirlik_yaklasik_mi = sektor_agirliklari()
    atlanan = []
    ham = []  # ilk gecis: sadece ham X/Y degerleri (koordinat henuz yok)

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
        x_trail = y_trail = None
        if trail_i - Y_PENCERE_HAFTA >= 0 and x_serisi[trail_i] is not None and x_serisi[trail_i - Y_PENCERE_HAFTA] is not None:
            x_trail = x_serisi[trail_i]
            y_trail = x_serisi[trail_i] - x_serisi[trail_i - Y_PENCERE_HAFTA]

        agirlik = agirliklar.get(kod)
        ham.append({
            "kod": kod, "ad": sek_ad, "agirlik": agirlik,
            "x_simdi": x_simdi, "y_simdi": y_simdi,
            "x_trail": x_trail, "y_trail": y_trail,
        })

    if not ham:
        raise SystemExit("Hicbir sektor icin rotasyon hesaplanamadi (yetersiz gecmis veri).")

    # Ikinci gecis: TUM sektorlerin ham degerlerini bilerek sira-tabanli koordinat hesapla.
    tum_x_simdi = [h["x_simdi"] for h in ham]
    tum_y_simdi = [h["y_simdi"] for h in ham]
    tum_x_trail = [h["x_trail"] for h in ham if h["x_trail"] is not None]
    tum_y_trail = [h["y_trail"] for h in ham if h["y_trail"] is not None]

    sonuc = []
    for h in ham:
        cx, cy = koordinat_hesapla_rank(h["x_simdi"], h["y_simdi"], tum_x_simdi, tum_y_simdi)
        evre = evre_belirle(h["x_simdi"], h["y_simdi"])
        if h["x_trail"] is not None and h["y_trail"] is not None:
            cx_trail, cy_trail = koordinat_hesapla_rank(h["x_trail"], h["y_trail"], tum_x_trail, tum_y_trail)
        else:
            cx_trail, cy_trail = None, None

        sonuc.append({
            "kod": h["kod"],
            "ad": h["ad"],
            "evre": evre,
            "x_goreli_guc_13hf": round(h["x_simdi"], 2),
            "y_momentum_4hf": round(h["y_simdi"], 2),
            "cx": cx, "cy": cy,
            "cx_3ay_once": cx_trail, "cy_3ay_once": cy_trail,
            "yaricap": bubble_yaricap(h["agirlik"]),
            "agirlik": h["agirlik"],
        })

    cikti = {
        "guncelleme": datetime.now(timezone.utc).isoformat(),
        "agirlik_yaklasik_mi": agirlik_yaklasik_mi,
        "not": (
            "GNC Insight'in kendi sadelestirilmis rotasyon okumasi. Egitim ve "
            "arastirma amaclidir, yatirim tavsiyesi degildir."
        ),
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
