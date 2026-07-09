# -*- coding: utf-8 -*-
"""
GNC Insight - Reel Getiri Deflatoru Cekici (TCMB EVDS)
Enflasyon (TUFE), USD/TRY ve gram altin aylik serilerini EVDS'ten ceker;
her horizon (1A / 3A / YBB / 1Y) icin yuzde degisim hesaplar ve ham aylik
seriyi de yazar. Panel bu deflator.json'u nominal getirilerle birlestirip
reel getiriyi tarayicida hesaplar.

Kaynak: TCMB EVDS v3. Anahtar EVDS_API_KEY ortam degiskeninden okunur
(GitHub Actions secret). evds paketi kullanilir.

Seri kodlari:
  TUFE (2003=100 endeks) : TP.FG.J0          [KESIN]
  USD/TRY (aylik ort.)   : TP.DK.USD.A.YTL   [KESIN]
  Gram altin TL          : ALTIN_SERI (asagida) [DOGRULANACAK]
      -> Actions ilk calistiginda log'a bak. Kod yanlissa altin null gelir,
         pipeline kirilmaz. Dogru kodu bulmak icin (borsapy kuruluysa):
             import borsapy as bp; print(bp.evds_search("altin"))
         ve ALTIN_SERI'yi guncelle.
"""

import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from evds import evdsAPI

KLASOR = Path(__file__).parent
HEDEF = KLASOR / "gnc-panel" / "deflator.json"

# --- Seri kodlari ---
TUFE_SERI = "TP.FG.J0"          # TUFE genel endeks (2003=100), aylik
USD_SERI = "TP.DK.USD.A.YTL"    # ABD Dolari alis, gunluk (aylik ort. cekilir)
ALTIN_SERI = "TP.MK.CUM.YTL"    # Gram altin adayi -- DOGRULANACAK (bkz. ust not)

# frequency: 5 = Aylik (evds paketi bu kodu kullanir)
FREQ_AYLIK = 5


def _key():
    k = os.environ.get("EVDS_API_KEY", "").strip()
    if not k:
        raise SystemExit("EVDS_API_KEY ortam degiskeni bulunamadi (GitHub secret).")
    return k


def _seri_cek(evds, kod, bas, bit):
    """Tek seriyi aylik ceker -> [{'tarih':'YYYY-MM','deger':float}, ...] (yeni->eski).
    Hata olursa bos liste doner (pipeline kirilmaz)."""
    try:
        df = evds.get_data([kod], startdate=bas, enddate=bit, frequency=FREQ_AYLIK)
    except Exception as e:
        print(f"  {kod}: cekilemedi ({e})")
        return []
    if df is None or not len(df):
        print(f"  {kod}: bos")
        return []
    # evds kolon adini nokta yerine alt cizgi ile verir: TP_FG_J0
    kol = kod.replace(".", "_")
    tar_kol = "Tarih" if "Tarih" in df.columns else df.columns[0]
    if kol not in df.columns:
        # tek veri kolonu varsa onu al
        adaylar = [c for c in df.columns if c not in (tar_kol, "YEARWEEK", "UNIXTIME")]
        if not adaylar:
            print(f"  {kod}: deger kolonu yok")
            return []
        kol = adaylar[-1]
    seri = []
    for _, r in df.iterrows():
        try:
            v = float(r[kol])
        except (TypeError, ValueError):
            continue
        if pd.isna(v):
            continue
        t = str(r[tar_kol]).strip()  # "2026-6" ya da "2026-06"
        parca = t.replace(".", "-").split("-")
        if len(parca) >= 2:
            yil, ay = parca[0], parca[1].zfill(2)
            seri.append({"tarih": f"{yil}-{ay}", "deger": round(v, 4)})
    # yeni -> eski sirala
    seri.sort(key=lambda x: x["tarih"], reverse=True)
    print(f"  {kod}: {len(seri)} aylik gozlem")
    return seri


def _yuzde(son, onceki):
    if son is None or onceki in (None, 0):
        return None
    return round((son / onceki - 1) * 100, 2)


def _ay_geri(seri, n):
    """seri: yeni->eski. n ay onceki degeri getir (yoksa None)."""
    return seri[n]["deger"] if len(seri) > n else None


def _ybb_baz(seri):
    """Bu yilin baslangic bazi = gecen yilin Aralik endeksi (YBB icin dogru baz).
    Bulunamazsa bu yilin ilk gozlemi."""
    if not seri:
        return None
    son_yil = int(seri[0]["tarih"][:4])
    aralik = f"{son_yil - 1}-12"
    for x in seri:
        if x["tarih"] == aralik:
            return x["deger"]
    # fallback: bu yilin en eski ayi
    bu_yil = [x for x in seri if x["tarih"][:4] == str(son_yil)]
    return bu_yil[-1]["deger"] if bu_yil else None


def _horizonlar(seri):
    """seri (yeni->eski) icin 1A/3A/YBB/1Y yuzde degisim."""
    if len(seri) < 2:
        return {"1a": None, "3a": None, "ybb": None, "1y": None, "son": None, "son_tarih": None}
    son = seri[0]["deger"]
    return {
        "son": son,
        "son_tarih": seri[0]["tarih"],
        "1a": _yuzde(son, _ay_geri(seri, 1)),
        "3a": _yuzde(son, _ay_geri(seri, 3)),
        "ybb": _yuzde(son, _ybb_baz(seri)),
        "1y": _yuzde(son, _ay_geri(seri, 12)),
    }


def main():
    evds = evdsAPI(_key())
    yil = datetime.now().year
    bas = f"01-01-{yil - 2}"                 # 2 yil geriye (1Y + YBB icin bol pay)
    bit = datetime.now().strftime("%d-%m-%Y")

    print("EVDS deflator serileri cekiliyor...")
    tufe = _seri_cek(evds, TUFE_SERI, bas, bit)
    usd = _seri_cek(evds, USD_SERI, bas, bit)
    altin = _seri_cek(evds, ALTIN_SERI, bas, bit)

    cikti = {
        "guncelleme": datetime.now().isoformat(),
        "kaynak": "TCMB EVDS",
        "not": "Aylik seriler. Reel getiri = (1+nominal)/(1+deflator)-1. Gunluk/haftalik reel getiri anlamsizdir (enflasyon aylik).",
        "deflatorler": {
            "tufe": {"ad": "TÜFE (Enflasyon)", "seri_kod": TUFE_SERI, **_horizonlar(tufe), "seri": tufe[:24]},
            "usd": {"ad": "USD/TRY", "seri_kod": USD_SERI, **_horizonlar(usd), "seri": usd[:24]},
            "altin": {"ad": "Gram Altın", "seri_kod": ALTIN_SERI, **_horizonlar(altin), "seri": altin[:24]},
        },
    }

    HEDEF.parent.mkdir(parents=True, exist_ok=True)
    HEDEF.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")

    ozet = {k: v.get("1y") for k, v in cikti["deflatorler"].items()}
    print(f"\nTamamlandi -> {HEDEF}")
    print(f"  1Y degisim: TÜFE={ozet['tufe']}%  USD={ozet['usd']}%  Altın={ozet['altin']}%")
    if not altin:
        print("  UYARI: Altin serisi bos. ALTIN_SERI kodunu dogrula (bkz. dosya basi notu).")


if __name__ == "__main__":
    main()
