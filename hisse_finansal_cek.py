# -*- coding: utf-8 -*-
"""
GNC Insight - Hisse Finansal Cekici (ARTIMLI / INCREMENTAL)

SORUN (14 Tem 2026): Eski surum HER CALISMADA 466 hissenin 10 YILLIK
gecmisini, 3 ayri format grubunda (3/2/1) bastan cekiyordu - ustelik eksik
kalanlar icin 3 grubu BIR KEZ DAHA tariyordu. Sonuc: ~4 SAAT ve GitHub
Actions dakika kotasinin buyuk kismi.

COZUM: Gecmis bilancolar DEGISMEZ. Elimizde zaten var. Bu yuzden:
  1. Her hisse icin mevcut finansal/{KOD}.json'a bakilir
  2. Zaten EN SON beklenen ceyregi iceriyorsa -> HIC CEKILMEZ (atlanir)
  3. Eksikse -> SADECE SON 2 YIL cekilir ve mevcut veriyle BIRLESTIRILIR
     (eski donemler korunur, yenisi eklenir/guncellenir)

Boylece tipik bir calismada (bilanco donemi disinda) neredeyse HICBIR
istek atilmaz - saniyeler icinde biter.

TAM YENILEME: workflow_dispatch ile TAM_YENILEME=1 verilirse eski davranis
(her seyi bastan cek) calisir. Bu gerekli cunku:
  - TMS 29 enflasyon muhasebesi GECMIS donemleri de yeniden ifade edebiliyor
  - Yeni hisse eklendiginde tum gecmisi lazim
Ayda bir tam yenileme onerilir (ayri cron ile).
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from isyatirimhisse import fetch_financials

KLASOR = Path(__file__).parent
FINANSAL_KLASOR = KLASOR / "gnc-panel" / "finansal"
BASE_COLS = {"SYMBOL", "FINANCIAL_ITEM_CODE", "FINANCIAL_ITEM_NAME_TR", "FINANCIAL_ITEM_NAME_EN"}
DONEM_SAYISI = 40   # ~10 yil (ceyreklik) - TAM YENILEMEDE saklanacak donem sayisi
GRUP_BOYUT = 40     # tek istekte kac sembol (25->40, daha az istek)
PARALEL = 6         # es zamanli istek sayisi.
                    # 4 -> 6 (16 Agu 2026). piyasa_cek.py 4 ile sorunsuz calisiyor;
                    # 6'da hata orani artarsa (loglarda cok sayida "hata" satiri)
                    # 4'e geri dusurun - Is Yatirim rate-limit uygulayabilir.
MIN_KALEM = 10
ARTIMLI_GERI_YIL = 2  # artimli modda kac yil geriye bakilir (guvenli pay)

TAM_YENILEME = os.environ.get("TAM_YENILEME", "").strip() in ("1", "true", "True", "evet")

# KADEMELI TAM YENILEME (16 Agu 2026)
# Sorun: Tam yenileme TEK SEFERDE 4-6 saat suruyordu. Bu sure boyunca:
#   - baska bir workflow ayni dosyalari yazarsa git catismasi cikiyor
#   - tek bir hata tum calismayi cope atiyor
#   - kota tek kalemde buyuk darbe aliyor
# Cozum: hisseleri DILIMLERE bolup her hafta bir dilimi yenilemek.
# Ayda 4 calisma x ~25 dk = ayni is, ama her biri kisa ve guvenli.
# TAM_DILIM=0 -> dilimleme YOK, hepsi tek seferde (eski davranis)
TAM_DILIM = int(os.environ.get("TAM_DILIM", "0") or 0)
TAM_DILIM_SAYISI = int(os.environ.get("TAM_DILIM_SAYISI", "4") or 4)


def hisse_kodlari():
    veri = json.loads((KLASOR / "gnc-panel" / "sektor_hisseler.json").read_text(encoding="utf-8"))
    kodlar = []
    for grup in veri["hisseler"].values():
        for h in grup:
            kodlar.append(h["kod"])
    return sorted(set(kodlar))


def temizle_deger(x):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    try:
        return round(float(x), 0)
    except Exception:
        return None


def donem_anahtari(c):
    try:
        y, q = str(c).split("/")
        return (int(y), int(q))
    except Exception:
        return (0, 0)


def beklenen_son_donem():
    """Bugun itibariyle KAP'ta yayinlanmis olmasi BEKLENEN en son ceyrek.
    Bilancolar ceyrek bitiminden ~2-3 ay sonra aciklanir, bu yuzden
    GUVENLI bir gecikme payi birakiyoruz (bugunden 4 ay geri gidip o
    ceyrege bakiyoruz). Bu, "bosuna cekme" ile "yeni bilancoyu kacirma"
    arasindaki dengeyi kurar."""
    bugun = datetime.now()
    ay = bugun.month - 4
    yil = bugun.year
    if ay <= 0:
        ay += 12
        yil -= 1
    ceyrek_ay = ((ay - 1) // 3) * 3 + 3  # 3, 6, 9, 12
    return (yil, ceyrek_ay)


def mevcut_veriyi_yukle(kod):
    yol = FINANSAL_KLASOR / f"{kod}.json"
    if not yol.exists():
        return None
    try:
        return json.loads(yol.read_text(encoding="utf-8"))
    except Exception:
        return None


def guncel_mi(mevcut, hedef_donem):
    """Mevcut veri, beklenen son ceyregi ZATEN iceriyor mu?"""
    if not mevcut or not mevcut.get("kalemler"):
        return False
    tum_donemler = set()
    for k in mevcut["kalemler"]:
        tum_donemler.update(k.get("degerler", {}).keys())
    if not tum_donemler:
        return False
    en_son = max((donem_anahtari(d) for d in tum_donemler), default=(0, 0))
    return en_son >= hedef_donem


def parcala(df, donem_limiti=None):
    """Coklu-sembol DataFrame -> {KOD: {donemler, kalemler}}."""
    sonuc = {}
    if df is None or not len(df) or "SYMBOL" not in df.columns:
        return sonuc
    donem_kol = [c for c in df.columns if c not in BASE_COLS and re.match(r"^\d{4}/\d{1,2}$", str(c))]
    donem_kol = sorted(donem_kol, key=donem_anahtari, reverse=True)
    if donem_limiti:
        donem_kol = donem_kol[:donem_limiti]

    for kod, grp in df.groupby("SYMBOL"):
        kalemler = []
        for _, r in grp.iterrows():
            ad = r.get("FINANCIAL_ITEM_NAME_TR")
            if not ad:
                continue
            degerler = {}
            for d in donem_kol:
                v = temizle_deger(r.get(d))
                if v is not None:
                    degerler[d] = v
            if degerler:
                kalemler.append({"ad": str(ad).strip(), "degerler": degerler})
        if kalemler:
            sonuc[str(kod).strip()] = {"donemler": donem_kol, "kalemler": kalemler}
    return sonuc


def birlestir(mevcut, yeni):
    """YENI veriyi MEVCUT'un uzerine birlestirir. Eski donemler KORUNUR,
    yeni donemler eklenir, cakisan donemler YENI ile guncellenir (TMS 29
    yeniden ifade gibi durumlar icin yeni veri daha dogrudur)."""
    if not mevcut or not mevcut.get("kalemler"):
        return yeni

    kalem_harita = {k["ad"]: k for k in mevcut["kalemler"]}
    for yk in yeni.get("kalemler", []):
        ad = yk["ad"]
        if ad in kalem_harita:
            kalem_harita[ad]["degerler"].update(yk["degerler"])
        else:
            kalem_harita[ad] = yk

    # Donem sayisini sinirla (dosya sinirsiz buyumesin)
    tum_donemler = set()
    for k in kalem_harita.values():
        tum_donemler.update(k["degerler"].keys())
    tutulacak = set(sorted(tum_donemler, key=donem_anahtari, reverse=True)[:DONEM_SAYISI])

    kalemler = []
    for k in kalem_harita.values():
        k["degerler"] = {d: v for d, v in k["degerler"].items() if d in tutulacak}
        if k["degerler"]:
            kalemler.append(k)

    return {
        "donemler": sorted(tutulacak, key=donem_anahtari, reverse=True),
        "kalemler": kalemler,
    }


def _parca_cek(parca, yil_bas, yil_bit, grup, donem_limiti, etiket):
    """Tek bir sembol grubunu ceker. Hata olursa bos doner - pipeline kirilmaz."""
    try:
        df = fetch_financials(symbols=parca, start_year=yil_bas, end_year=yil_bit, financial_group=grup)
        cikan = parcala(df, donem_limiti)
        print(f"  grup {grup} [{etiket}]: {len(cikan)} hisse")
        return cikan
    except Exception as e:
        print(f"  grup {grup} [{etiket}] hata: {str(e)[:80]}")
        return {}


def toplu_cek(kodlar, yil_bas, yil_bit, grup, donem_limiti=None):
    """PARALEL cekim (16 Agu 2026): eskiden istekler SIRAYLA gidiyordu ve tam
    yenileme 5.5 SAAT suruyordu. piyasa_cek.py'de zaten kanitlanmis olan 4
    paralel istek desenini buraya da uyguladik + grup boyutu 25'ten 40'a
    cikarildi. Beklenen: ~4 kat hizlanma."""
    bulunan = {}
    parcalar = []
    for i in range(0, len(kodlar), GRUP_BOYUT):
        parca = kodlar[i:i + GRUP_BOYUT]
        parcalar.append((parca, f"{parca[0]}..{parca[-1]}"))

    if not parcalar:
        return bulunan

    with ThreadPoolExecutor(max_workers=PARALEL) as havuz:
        isler = {
            havuz.submit(_parca_cek, parca, yil_bas, yil_bit, grup, donem_limiti, etiket): etiket
            for parca, etiket in parcalar
        }
        for is_ in as_completed(isler):
            bulunan.update(is_.result())
    return bulunan


def main():
    kodlar = hisse_kodlari()
    yil = datetime.now().year
    FINANSAL_KLASOR.mkdir(parents=True, exist_ok=True)

    # Hisseleri UC gruba ayir:
    #   tam_gerekli -> dosyasi HIC YOK (YENI hisse) ya da TAM_YENILEME modu
    #                  -> 10 YIL cekilmeli. (KRITIK: yeni hisseye sadece 2 yil
    #                  cekmek gecmisini kalici olarak eksik birakirdi!)
    #   artimli     -> dosyasi var ama son ceyrek eksik -> 2 yil cek + BIRLESTIR
    #   atlanan     -> zaten guncel -> HIC CEKME (asil tasarruf burada)
    tam_gerekli, artimli, atlanan = [], [], 0
    if TAM_YENILEME:
        if TAM_DILIM and 1 <= TAM_DILIM <= TAM_DILIM_SAYISI:
            # Alfabetik siraya gore her N'inci hisse -> dilimler dengeli dagilir
            tam_gerekli = [k for i, k in enumerate(kodlar)
                           if i % TAM_DILIM_SAYISI == (TAM_DILIM - 1)]
            print(f"=== TAM YENILEME - DILIM {TAM_DILIM}/{TAM_DILIM_SAYISI} "
                  f"({len(tam_gerekli)}/{len(kodlar)} hisse) ===")
            print("    Diger dilimler sonraki calismalarda yenilenecek.")
        else:
            tam_gerekli = list(kodlar)
            print("=== TAM YENILEME MODU (TUMU tek seferde - UZUN SURER) ===")
    else:
        hedef = beklenen_son_donem()
        print(f"=== ARTIMLI MOD - beklenen son donem: {hedef[0]}/{hedef[1]} ===")
        for kod in kodlar:
            mevcut = mevcut_veriyi_yukle(kod)
            if mevcut is None or not mevcut.get("kalemler"):
                tam_gerekli.append(kod)   # YENI hisse - tum gecmis lazim
            elif guncel_mi(mevcut, hedef):
                atlanan += 1
            else:
                artimli.append(kod)
        print(f"{atlanan} hisse ZATEN GUNCEL (hic cekilmeyecek)")
        print(f"{len(tam_gerekli)} YENI hisse (10 yil), {len(artimli)} hisse artimli guncellenecek")
        if not tam_gerekli and not artimli:
            print("\nHicbir hisse guncelleme gerektirmiyor - is bitti (0 istek atildi).")
            return

    # Grup onceligi: 3 = UFRS Konsolide, 2 = UFRS (solo), 1 = eski XI_29.
    # KRITIK: Bir hissenin HANGI grupta cekildigini kaydediyoruz ("kaynak_grup").
    # Artimli guncellemede AYNI grup tercih edilir - yoksa ayni dosyada IKI FARKLI
    # muhasebe formatinin kalem adlari karisir (orn. eski XI_29 banka kalemleri +
    # yeni UFRS kalemleri ayni dosyada) ve asagi akistaki hesaplar bozulur.
    veriler = {}
    kullanilan_grup = {}

    def gruplu_cek(hedef_kodlar, yil_bas, donem_limiti, tercih=None):
        for grup in ("3", "2", "1"):
            kalan = [k for k in hedef_kodlar if k not in veriler]
            if tercih is not None:
                kalan = [k for k in kalan if tercih.get(k) == grup]
            if not kalan:
                continue
            print(f"  Grup {grup}: {len(kalan)} hisse deneniyor...")
            yeni = toplu_cek(kalan, yil_bas, yil, grup, donem_limiti)
            for kod, fin in yeni.items():
                if len(fin.get("kalemler", [])) >= MIN_KALEM:
                    veriler[kod] = fin
                    kullanilan_grup[kod] = grup

    if tam_gerekli:
        print(f"TAM cekim ({len(tam_gerekli)} hisse, 10 yil)...")
        gruplu_cek(tam_gerekli, yil - 10, DONEM_SAYISI)

    if artimli:
        print(f"ARTIMLI cekim ({len(artimli)} hisse, {ARTIMLI_GERI_YIL} yil)...")
        tercih = {}
        for kod in artimli:
            m = mevcut_veriyi_yukle(kod)
            if m and m.get("kaynak_grup"):
                tercih[kod] = m["kaynak_grup"]
        if tercih:
            gruplu_cek([k for k in artimli if k in tercih], yil - ARTIMLI_GERI_YIL, None, tercih)
        gruplu_cek([k for k in artimli if k not in veriler], yil - ARTIMLI_GERI_YIL, None)

    # NOT: Eski surumdeki "esigi dusurup 3 grubu BIR KEZ DAHA tara" adimi
    # KALDIRILDI - calisma suresini IKIYE KATLIYORDU, kazanci minimaldi.
    # Bulunamayan hisseler sonraki calismada zaten tekrar denenecek.

    ok, birlesen, format_degisti, gerileme = 0, 0, 0, 0
    now = datetime.now().isoformat()
    for kod, fin in veriler.items():
        # SADECE artimli guncellenen hisselerde birlestir. TAM cekilenlerde
        # (yeni hisse / TAM_YENILEME) birlestirme YAPILMAZ - taze veri zaten
        # tum gecmisi iceriyor, birlestirmek eski kalem adlarini tasirdi.
        if kod in artimli and not TAM_YENILEME:
            mevcut = mevcut_veriyi_yukle(kod)
            onceki_grup = (mevcut or {}).get("kaynak_grup")
            simdiki_grup = kullanilan_grup.get(kod)
            if onceki_grup and simdiki_grup and onceki_grup != simdiki_grup:
                # GUVENLIK: grup degistiyse BIRLESTIRME - iki farkli muhasebe
                # formati karisirsa dosya bozulur. Dosyayi tamamen yeni (2 yillik
                # ama TUTARLI) veriyle degistiriyoruz; aylik TAM YENILEME gecmisi
                # zaten geri getirecek.
                print(f"  UYARI: {kod} muhasebe grubu degisti ({onceki_grup} -> {simdiki_grup}) - birlestirilmedi, dosya yenilendi")
                format_degisti += 1
            elif mevcut:
                fin = birlestir(mevcut, fin)
                birlesen += 1
        # GERILEME KORUMASI (29 Agu 2026)
        # BULUNAN RISK: TAM_YENILEME modunda birlestirme YAPILMIYOR - dosya
        # taze cekimle tamamen degistiriliyor. Hisse icin HIC veri gelmezse
        # dosya korunuyor (guvenli). Ama KISMI veri gelirse - orn. 2024 ve
        # 2026 gelip 2025 gelmezse - dosya o eksik veriyle uzerine yaziliyor
        # ve mevcut donemler SILINIYOR.
        # GARAN'in 2025'inin tamamen bos olmasi buyuk olasilikla boyle olustu:
        # 34 donem, digir bankalarda 40. Ayni grup (3), ayni guncelleme tarihi.
        # Yani pahali calistirma veriyi DUZELTMEK yerine BOZABILIYOR.
        # Kural: taze cekim mevcut dosyadan DAHA AZ donem tasiyorsa yazma.
        # Muhasebe grubu degistiyse istisna - o zaman az donem NORMALDIR,
        # cunku dosya bilerek yenileniyor.
        mevcut_kontrol = mevcut_veriyi_yukle(kod)
        if mevcut_kontrol:
            eski_n = len(mevcut_kontrol.get("donemler", []))
            yeni_n = len(fin.get("donemler", []))
            grup_ayni = (mevcut_kontrol.get("kaynak_grup") == kullanilan_grup.get(kod))
            if grup_ayni and yeni_n < eski_n:
                print(f"  KORUMA: {kod} taze cekim {yeni_n} donem, mevcut {eski_n} - "
                      f"GERILEME, dosya korundu")
                gerileme += 1
                continue
        fin["kod"] = kod
        fin["kaynak_grup"] = kullanilan_grup.get(kod)
        fin["guncelleme"] = now
        (FINANSAL_KLASOR / f"{kod}.json").write_text(json.dumps(fin, ensure_ascii=False), encoding="utf-8")
        ok += 1

    denenen = tam_gerekli + artimli
    bulunamayan = [k for k in denenen if k not in veriler]
    print(f"\nTamamlandi: {ok} hisse yazildi ({birlesen} birlestirildi, "
          f"{format_degisti} format degisimi)")
    if gerileme:
        print(f"  KORUMA: {gerileme} hissede taze cekim mevcuttan AZ donem tasiyordu, "
              f"dosyalari korundu (veri kaybi onlendi)")
    if bulunamayan:
        ornek = ', '.join(bulunamayan[:10]) + ('...' if len(bulunamayan) > 10 else '')
        print(f"  {len(bulunamayan)} hisse icin veri gelmedi (sonraki calismada tekrar denenecek): {ornek}")


if __name__ == "__main__":
    main()
