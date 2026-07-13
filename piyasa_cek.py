# -*- coding: utf-8 -*-
"""
GNC Insight - Piyasa Verisi Cekici (Sektor + Hisse, TEK RUN, AYNI AN) - DAYANIKLI
Eskiden sektor_cek.py ve hisse_veri_cek.py ayri ayri calisirdi; endeksler TEK TEK
(26 istek x retry) cekildigi icin dakikalar surebiliyor, bu sirada hisse fiyati
henuz cekilmemis oluyordu -> panelde endeks yesil, hisse eski/kirmizi gorunuyordu.

Bu script:
1) Once bir "guncelleme" zaman damgasi alir (hem sektor hem hisse dosyasi BU
   damgayi tasir -> panelde ayni ana ait oldugu garanti edilir).
2) Endeksleri TOPLU (tek istekte tum 27 endeks) ceker; basarisiz olursa TEK
   TEK retry'a duser (eski dayaniklilik korunur).
3) Hemen ardindan hisseleri gruplar halinde ceker (mevcut mantik).
4) Her iki dosyayi da ayni calismanin sonunda, ayni timestamp ile yazar.

DEGISIKLIK (13 Tem 2026): HAO_PD (halka aciklik oranina gore DUZELTILMIS
piyasa degeri) artik ayri bir "hao_pd" alani olarak da yakalaniyor. Onceden
pd_k = kolon_bul(df, ["PD", "PD_TL", "HAO_PD", "HG_PD"]) sirasinda "PD" ilk
sirada oldugu icin HAO_PD'ye hic sira gelmiyordu, sessizce hic kullanilmiyordu.
Simdi "pd" (ham, PD/DD gibi TOPLAM piyasa degeri gerektiren hesaplar icin) ve
"hao_pd" (sektor AGIRLIGI gibi halka-acik-kisim gerektiren hesaplar icin)
AYRI alanlar olarak tutuluyor - biri digerinin yerini almiyor, ikisi de var.

Onceki iki script (sektor_cek.py, hisse_veri_cek.py) artik KULLANILMIYOR;
workflow bu dosyayi cagirir.
"""

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from isyatirimhisse import fetch_index_data, fetch_stock_data

KLASOR = Path(__file__).parent

ENDEKSLER = [
    ("XU100", "BIST 100", "referans"),
    ("XUSIN", "Sinai", "ana_grup"),
    ("XUMAL", "Mali", "ana_grup"),
    ("XUHIZ", "Hizmetler", "ana_grup"),
    ("XUTEK", "Teknoloji", "ana_grup"),
    ("XBANK", "Bankacilik", "sektor"),
    ("XSGRT", "Sigorta", "sektor"),
    ("XFINK", "Fin. Kiralama Faktoring", "sektor"),
    ("XHOLD", "Holding ve Yatirim", "sektor"),
    ("XGYO", "Gayrimenkul Yat. Ort.", "sektor"),
    ("XYORT", "Menkul Kiymet Yat. Ort.", "sektor"),
    ("XGIDA", "Gida ve Icecek", "sektor"),
    ("XKMYA", "Kimya Petrol Plastik", "sektor"),
    ("XMANA", "Metal Ana Sanayi", "sektor"),
    ("XMESY", "Metal Esya Makina", "sektor"),
    ("XTAST", "Tas Toprak (Cam Cimento)", "sektor"),
    ("XTEKS", "Tekstil ve Deri", "sektor"),
    ("XKAGT", "Orman Kagit Basim", "sektor"),
    ("XELKT", "Elektrik", "sektor"),
    ("XILTM", "Iletisim", "sektor"),
    ("XULAS", "Ulastirma", "sektor"),
    ("XTCRT", "Ticaret", "sektor"),
    ("XTRZM", "Turizm", "sektor"),
    ("XINSA", "Insaat ve Bayindirlik", "sektor"),
    ("XMADN", "Madencilik", "sektor"),
    ("XBLSM", "Bilisim", "sektor"),
    ("XSPOR", "Spor", "sektor"),
]
DONEMLER = ("g1", "h1", "a1", "a3", "ybb")
DENEME = 3
BEKLE = 2

HISSE_GRUP_BOYUT = 50
PARALEL_ISCI = 4  # ayni anda kac grup istegi atilsin (Is Yatirim'i asiri yuklememek icin sinirli)


# ---------------- ORTAK ----------------

def yuzde(son, onceki):
    if son is None or onceki in (None, 0) or (isinstance(onceki, float) and math.isnan(onceki)):
        return None
    return round((son / onceki - 1) * 100, 2)


def hisse_kodlari():
    veri = json.loads((KLASOR / "gnc-panel" / "sektor_hisseler.json").read_text(encoding="utf-8"))
    kodlar = []
    for grup in veri["hisseler"].values():
        for h in grup:
            kodlar.append(h["kod"])
    return sorted(set(kodlar))


# ---------------- SEKTOR (ENDEKS) ----------------

def endeks_getiri_hesapla(kapanis, tarih):
    c = [(t, v) for t, v in zip(tarih, kapanis) if v is not None]
    if len(c) < 2:
        return {}
    tarih = [t for t, _ in c]
    c = [v for _, v in c]
    son = c[-1]
    geri = lambda n: c[-1 - n] if len(c) > n else None
    son_yil = tarih[-1].year
    ilk_bu_yil = next((c[i] for i in range(len(tarih)) if tarih[i].year == son_yil), None)
    return {
        "son_deger": round(float(son), 2),
        "g1": yuzde(son, geri(1)),
        "h1": yuzde(son, geri(5)),
        "a1": yuzde(son, geri(21)),
        "a3": yuzde(son, geri(63)),
        "ybb": yuzde(son, ilk_bu_yil),
    }


def endeks_eski_yukle(hedef):
    eski = {}
    if hedef.exists():
        try:
            data = json.loads(hedef.read_text(encoding="utf-8"))
            for e in data.get("endeksler", []):
                if e.get("kod"):
                    eski[e["kod"]] = e
        except Exception as e:
            print(f"Eski sektor dosyasi okunamadi: {e}")
    return eski


def endeks_toplu_cek(kodlar, baslangic, bitis):
    """Tum endeksleri TEK istekte ceker. Basarisizsa None doner (tek-tek retry'a duser)."""
    try:
        df = fetch_index_data(indices=kodlar, start_date=baslangic, end_date=bitis)
        if df is not None and len(df):
            return df
    except Exception as e:
        print(f"  toplu endeks cekimi hata: {str(e)[:100]}")
    return None


def endeks_tek_cek(kod, baslangic, bitis):
    for i in range(DENEME):
        try:
            df = fetch_index_data(indices=[kod], start_date=baslangic, end_date=bitis)
            if df is not None and len(df):
                return df
        except Exception as e:
            print(f"  {kod:6s} deneme {i+1}/{DENEME} hata: {str(e)[:70]}")
        if i < DENEME - 1:
            time.sleep(BEKLE)
    return None


def sektor_calistir(now_iso):
    hedef = KLASOR / "gnc-panel" / "sektor_verisi.json"
    hedef.parent.mkdir(parents=True, exist_ok=True)
    eski = endeks_eski_yukle(hedef)

    bugun = datetime.now()
    baslangic = (bugun - timedelta(days=400)).strftime("%d-%m-%Y")
    bitis = bugun.strftime("%d-%m-%Y")
    kodlar = [k for k, _, _ in ENDEKSLER]
    ad_tip = {k: (a, t) for k, a, t in ENDEKSLER}

    print(f"{len(kodlar)} endeks TOPLU cekiliyor (Is Yatirim)...")
    df = endeks_toplu_cek(kodlar, baslangic, bitis)

    sonuclar = []
    taze_sayi = 0
    bulunanlar = set()

    if df is not None and "INDEX" in df.columns:
        for kod in kodlar:
            alt = df[df["INDEX"] == kod].sort_values("DATE")
            if len(alt) >= 2:
                kapanis = [float(v) for v in alt["VALUE"].tolist()]
                tarih = list(alt["DATE"].tolist())
                ad, tip = ad_tip[kod]
                kayit = {"kod": kod, "ad": ad, "tip": tip}
                kayit.update(endeks_getiri_hesapla(kapanis, tarih))
                sonuclar.append(kayit)
                bulunanlar.add(kod)
                taze_sayi += 1
        print(f"  toplu cekim: {taze_sayi}/{len(kodlar)} endeks tamam")

    eksikler = [k for k in kodlar if k not in bulunanlar]
    if eksikler:
        print(f"  {len(eksikler)} endeks tek tek deneniyor...")
        for kod in eksikler:
            df2 = endeks_tek_cek(kod, baslangic, bitis)
            ad, tip = ad_tip[kod]
            if df2 is not None:
                alt = df2[df2["INDEX"] == kod].sort_values("DATE")
                if len(alt) >= 2:
                    kapanis = [float(v) for v in alt["VALUE"].tolist()]
                    tarih = list(alt["DATE"].tolist())
                    kayit = {"kod": kod, "ad": ad, "tip": tip}
                    kayit.update(endeks_getiri_hesapla(kapanis, tarih))
                    sonuclar.append(kayit)
                    taze_sayi += 1
                    print(f"  {kod:6s} tek tek tamam")
                    continue
            if kod in eski:
                korunan = dict(eski[kod])
                korunan["ad"] = ad
                korunan["tip"] = tip
                sonuclar.append(korunan)
                print(f"  {kod:6s} taze gelmedi -> eski veri korundu")
            else:
                kayit = {"kod": kod, "ad": ad, "tip": tip, "son_deger": None, "hata": True}
                kayit.update({d: None for d in DONEMLER})
                sonuclar.append(kayit)
                print(f"  {kod:6s} veri yok (eski de yok)")

    if taze_sayi == 0:
        print("Sektor: hic taze veri gelmedi. Mevcut dosya KORUNUYOR (yazilmadi).")
        return False

    xu = next((s for s in sonuclar if s["kod"] == "XU100"), None)
    for s in sonuclar:
        for d in DONEMLER:
            if xu and s.get(d) is not None and xu.get(d) is not None:
                s["rol_" + d] = round(s[d] - xu[d], 2)
            else:
                s["rol_" + d] = None

    cikti = {"guncelleme": now_iso, "kaynak": "Is Yatirim", "endeksler": sonuclar}
    hedef.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")
    print(f"Sektor tamamlandi: {taze_sayi}/{len(kodlar)} TAZE -> {hedef}")
    return True


# ---------------- HISSE ----------------

def kolon_bul(df, adaylar):
    for a in adaylar:
        for c in df.columns:
            if str(c).upper() == a.upper():
                return c
    return None


def hisse_eski_yukle(hedef):
    if hedef.exists():
        try:
            data = json.loads(hedef.read_text(encoding="utf-8"))
            return data.get("hisseler", {}) or {}
        except Exception as e:
            print(f"Eski hisse dosyasi okunamadi: {e}")
    return {}


def hisse_grup_cek(kodlar, baslangic, bitis):
    for i in range(DENEME):
        try:
            df = fetch_stock_data(symbols=kodlar, start_date=baslangic, end_date=bitis)
            if df is not None and len(df):
                return df
        except Exception as e:
            print(f"  grup [{kodlar[0]}..{kodlar[-1]}] deneme {i+1}/{DENEME} hata: {str(e)[:60]}")
        if i < DENEME - 1:
            time.sleep(BEKLE)
    return None


def hisse_isle(df, kod, kod_k, kap_k, tar_k, hac_k, pd_k, hao_pd_k):
    if not kod_k:
        return None
    alt = df[df[kod_k] == kod].sort_values(tar_k)
    if len(alt) < 2:
        return None
    kapanis = [float(v) for v in alt[kap_k].tolist() if v is not None]
    if len(kapanis) < 2:
        return None
    son = kapanis[-1]
    geri = lambda n: kapanis[-1 - n] if len(kapanis) > n else None
    return {
        "fiyat": round(son, 2),
        "g1": yuzde(son, geri(1)),
        "h1": yuzde(son, geri(5)),
        "a1": yuzde(son, geri(21)),
        # pd = HAM (halka aciklik duzeltmesi yapilmamis) TOPLAM piyasa degeri.
        # PD/DD gibi "toplam ozkaynak/toplam piyasa degeri" hesaplarinda kullanilir.
        "pd": float(alt[pd_k].iloc[-1]) if pd_k and not pd.isna(alt[pd_k].iloc[-1]) else None,
        # hao_pd = halka aciklik oranina gore DUZELTILMIS piyasa degeri (12 Tem 2026'da
        # PD'den GERCEKTEN farkli oldugu dogrulandi - teshis_hao_pd.py ile). Sektor
        # AGIRLIGI (Rotasyon Saati baloncuk boyutu, Endekse Katki) icin bu kullanilmali.
        "hao_pd": float(alt[hao_pd_k].iloc[-1]) if hao_pd_k and not pd.isna(alt[hao_pd_k].iloc[-1]) else None,
        "hacim": float(alt[hac_k].iloc[-1]) if hac_k and not pd.isna(alt[hac_k].iloc[-1]) else None,
    }


def hisse_calistir(now_iso):
    kodlar = hisse_kodlari()
    bugun = datetime.now()
    baslangic = (bugun - timedelta(days=150)).strftime("%d-%m-%Y")
    bitis = bugun.strftime("%d-%m-%Y")

    hedef = KLASOR / "gnc-panel" / "sektor_hisse_veri.json"
    hedef.parent.mkdir(parents=True, exist_ok=True)
    eski = hisse_eski_yukle(hedef)

    print(f"{len(kodlar)} hisse {HISSE_GRUP_BOYUT}'li gruplarla, {PARALEL_ISCI} paralel istekle cekiliyor (Is Yatirim)...")
    sonuc = {}
    taze_sayi = 0

    gruplar = [kodlar[i:i + HISSE_GRUP_BOYUT] for i in range(0, len(kodlar), HISSE_GRUP_BOYUT)]

    def grup_isle(parca):
        df = hisse_grup_cek(parca, baslangic, bitis)
        if df is None:
            return parca, None
        kod_k = kolon_bul(df, ["HGDG_HS_KODU"])
        kap_k = kolon_bul(df, ["HGDG_KAPANIS"])
        tar_k = kolon_bul(df, ["HGDG_TARIH"])
        hac_k = kolon_bul(df, ["HGDG_HACIM", "HG_HACIM", "DOLAR_HACIM"])
        pd_k = kolon_bul(df, ["PD", "PD_TL", "HG_PD"])
        hao_pd_k = kolon_bul(df, ["HAO_PD"])
        grup_sonuc = {}
        for kod in parca:
            v = hisse_isle(df, kod, kod_k, kap_k, tar_k, hac_k, pd_k, hao_pd_k)
            if v is not None:
                grup_sonuc[kod] = v
        return parca, grup_sonuc

    with ThreadPoolExecutor(max_workers=PARALEL_ISCI) as havuz:
        gelecekler = {havuz.submit(grup_isle, parca): parca for parca in gruplar}
        for gelecek in as_completed(gelecekler):
            parca = gelecekler[gelecek]
            ilk, son = parca[0], parca[-1]
            try:
                _, grup_sonuc = gelecek.result()
            except Exception as e:
                print(f"  grup [{ilk}..{son}]: hata {str(e)[:60]}")
                continue
            if grup_sonuc is None:
                print(f"  grup [{ilk}..{son}]: taze gelmedi (eski korunacak)")
                continue
            sonuc.update(grup_sonuc)
            taze_sayi += len(grup_sonuc)
            print(f"  grup [{ilk}..{son}]: tamam ({len(grup_sonuc)} hisse)")

    korunan = 0
    for kod in kodlar:
        if kod not in sonuc:
            if kod in eski and eski[kod].get("fiyat") is not None:
                sonuc[kod] = eski[kod]
                korunan += 1
            else:
                sonuc[kod] = {"fiyat": None, "g1": None, "h1": None, "a1": None, "pd": None, "hao_pd": None, "hacim": None}

    if taze_sayi == 0:
        print("Hisse: hic taze veri gelmedi. Mevcut dosya KORUNUYOR (yazilmadi).")
        return False

    cikti = {"guncelleme": now_iso, "kaynak": "Is Yatirim", "hisseler": sonuc}
    hedef.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")
    print(f"Hisse tamamlandi: {taze_sayi} taze + {korunan} korunan / {len(kodlar)} -> {hedef}")
    return True


def main():
    now_iso = datetime.now(timezone.utc).isoformat()
    print(f"Calisma zamani (ortak damga): {now_iso}\n")

    print("=== SEKTOR (ENDEKS) ===")
    sektor_ok = sektor_calistir(now_iso)

    print("\n=== HISSE ===")
    hisse_ok = hisse_calistir(now_iso)

    if not sektor_ok and not hisse_ok:
        raise SystemExit("Hic taze veri gelmedi (sektor ve hisse). Actions basarisiz sayilacak.")


if __name__ == "__main__":
    main()
