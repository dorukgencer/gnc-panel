# -*- coding: utf-8 -*-
"""
GNC Insight - Finansal Tablo Kalem Haritasi (FORMAT FARKINDA)

SORUN:
  veri_denetim.py tek bir kalem adi listesi kullaniyordu. Ama BIST'te UC AYRI
  tablo formati var ve kalem adlari birbirini tutmuyor:

    SANAYI  (454 sirket) : "Ozkaynaklar", "Satis Gelirleri", "Donem Net Kar/Zarari"
    BANKA   ( 12 sirket) : "XVI. OZKAYNAKLAR", "XXIII. NET DONEM KARI/ZARARI"
    SIGORTA (  6 sirket) : "Ozsermaye Toplami", "N- Donem Net Kari veya Zarari"

  Bu yuzden denetim 18 sirketi "KRITIK - kalem bulunamadi" diye isaretliyordu.
  Veri eksik degildi; ARAYAN YANLIS YERDE ARIYORDU.

  Ayrica bu 18 sirket icin bazi olculer ANLAMSIZ:
    - Bankaya "Net Borc / FAVOK" uygulanamaz (kaldirac is modelidir)
    - Sigortaya "Satislar" uygulanamaz (teknik gelir vardir)
  Bu yuzden her formatin KENDI zorunlu kalem listesi var.

KULLANIM:
    from kalem_haritasi import format_belirle, kalem_bul, ZORUNLU

    fmt = format_belirle(veri)                  # "SANAYI" | "BANKA" | "SIGORTA"
    ok  = kalem_bul(veri, "ozkaynak", fmt)      # {"2026/6": 123.0, ...} veya None

NOT: Kalem adlari İş Yatırım'in dondurdugu adlardir. Ad degisirse buraya
     yeni aday eklemek yeterlidir; baska hicbir dosyaya dokunmak gerekmez.
"""

import unicodedata

# ---------------------------------------------------------------- format tespiti

# Her format icin "imza" kalemler: bunlardan biri varsa o formattir.
IMZA = {
    "BANKA": (
        "I. NAKİT DEĞERLER VE MERKEZ BANKASI",
        "XVI. ÖZKAYNAKLAR",
    ),
    "SIGORTA": (
        "Özsermaye Toplamı",
        "1- Sigortacılık Faaliyetlerinden Alacaklar",
    ),
}


def _sadelestir(s):
    """Karsilastirma icin: kucuk harf, Turkce harfleri sadelestir, bosluk temizle."""
    s = (s or "").strip().lower()
    s = s.replace("i̇", "i")
    d = {"ı": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c", "â": "a", "î": "i", "û": "u"}
    s = "".join(d.get(c, c) for c in s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.split())


def format_belirle(veri):
    """veri: finansal/{KOD}.json icerigi (dict). Doner: SANAYI | BANKA | SIGORTA."""
    adlar = {k.get("ad", "") for k in veri.get("kalemler", [])}
    sade = {_sadelestir(a) for a in adlar}
    for fmt, imzalar in IMZA.items():
        for im in imzalar:
            if _sadelestir(im) in sade:
                return fmt
    return "SANAYI"


# ---------------------------------------------------------------- kalem haritasi
# Her kanonik alan icin ADAY LISTESI. Sirali: ilk bulunan kazanir.
# Ana ortaklik payi tercih edilir (GNC kurali: net kar = Ana Ortaklik Paylari).

HARITA = {
    "SANAYI": {
        "ozkaynak":        ["Ana Ortaklığa Ait Özkaynaklar", "Özkaynaklar"],
        "net_kar":         ["Ana Ortaklık Payları", "Dönem Net Kar/Zararı",
                            "Dönem Karı (Zararı)", "Net Dönem Karı/Zararı"],
        "gelir":           ["Satış Gelirleri", "Hasılat", "Satışlar"],
        "faaliyet_kari":   ["Faaliyet Karı (Zararı)", "Esas Faaliyet Karı (Zararı)",
                            "Faaliyet Kârı (Zararı)", "Faaliyet Karı/Zararı"],
        "odenmis_sermaye": ["Ödenmiş Sermaye"],
        "brut_kar":        ["BRÜT KAR (ZARAR)", "Brüt Kar (Zarar)", "Brüt Kâr (Zarar)",
                            "Brüt Kar/Zarar"],
        # Finans segmenti olan holdinglerde (AHGAZ, DOHOL...) toplam brut kar
        #   = Ticari Faaliyetlerden Brut Kar + Finans Sektorunden Brut Kar
        # Muhasebe kimligi kontrolu SADECE ticari kisimla yapilmali; yoksa
        # sahte "%125 sapma" uyarisi uretir.
        "ticari_brut_kar": ["Ticari Faaliyetlerden Brüt Kar (Zarar)"],
        "finans_brut_kar": ["Finans Sektörü Faaliyetlerinden Brüt Kar (Zarar)"],
        "satis_maliyeti":  ["Satışların Maliyeti (-)", "Satışların Maliyeti"],
        "toplam_varlik":   ["Toplam Varlıklar", "TOPLAM VARLIKLAR", "Aktif Toplamı"],
        # TMS 29 parasal kazanc/kayip satiri bu veri setinde YOK; bulunan tek
        # ilgili kalem net yabanci para pozisyonu - dayaniklilik filtresinin girdisi.
        "net_yp_pozisyon": ["Parasal net yabancı para varlık/(yükümlülük) pozisyonu"],
        # --- turetilmis olculer icin gerekli kalemler (29 Agu 2026) ---
        "amortisman":      ["Amortisman & İtfa Payları", "Amortisman Giderleri"],
        "isletme_nakit":   ["İşletme Faaliyetlerinden Kaynaklanan Net Nakit"],
        "nakit":           ["Nakit ve Nakit Benzerleri"],
        # DIKKAT: "Finansal Borçlar" tabloda IKI KEZ gecer (kisa + uzun vadeli).
        # kalem_topla() ile TOPLANMALIDIR; kalem_bul() sadece ilkini (kisa vadeli)
        # dondurur ve borcu yariya indirir. Bu tuzak icin ozel fonksiyon var.
        "finansal_borc":   ["Finansal Borçlar"],
        "finansman_gideri":["Finansman Giderleri"],
        "fin_oncesi_fk":   ["Finansman Gideri Öncesi Faaliyet Karı/Zararı"],
    },
    "BANKA": {
        "ozkaynak":        ["XVI. ÖZKAYNAKLAR", "ÖZKAYNAK"],  # ÖZKAYNAK = katilim bankasi (ALBRK)
        "net_kar":         ["XXIII. NET DÖNEM KARI/ZARARI (XVII+XXII)",
                            "XVII. SÜRDÜRÜLEN FAALİYETLER DÖNEM NET K/Z (XV±XVI)"],
        # Bankada "satis" yoktur; faaliyet geliri toplami muadildir.
        "gelir":           ["VIII. FAALİYET GELİRLERİ/GİDERLERİ TOPLAMI (III+IV+V+VI+VII)",
                            "VIII. FAALİYET GELİRLERİ/GİDERLERİ TOPLAMI",
                            "III. NET FAİZ GELİRİ/GİDERİ (I - II)",
                            "III. NET KAR PAYI GELİRİ/GİDERİ (I-II)"],
        "faaliyet_kari":   ["XI. NET FAALİYET KARI/ZARARI (VIII-IX-X)"],
        "odenmis_sermaye": ["Ödenmiş Sermaye", "1.1 Ödenmiş Sermaye"],
        # Katilim bankasinda "faiz" degil "kar payi" denir - ikisi de aday.
        "net_faiz_geliri": ["III. NET FAİZ GELİRİ/GİDERİ (I - II)",
                            "III. NET KAR PAYI GELİRİ/GİDERİ (I-II)"],
        "net_parasal_poz": ["XIV. NET PARASAL POZİSYON KARI/ZARARI"],
    },
    "SIGORTA": {
        "ozkaynak":        ["Özsermaye Toplamı"],
        "net_kar":         ["N- Dönem Net Karı veya Zararı", "F-Dönem Net Karı",
                            "1- Dönem Net Karı", "3- Dönem Net Kar veya Zararı"],
        "gelir":           ["A- Hayat Dışı Teknik Gelir", "D- Hayat Teknik Gelir"],
        "odenmis_sermaye": ["A- Ödenmiş Sermaye"],
    },
}

# Her formatin KENDI zorunlu alanlari. Bir alan burada yoksa, o formatta
# bulunamamasi hata degildir - o format icin anlamsizdir.
ZORUNLU = {
    "SANAYI":  ["ozkaynak", "net_kar", "gelir", "odenmis_sermaye"],
    "BANKA":   ["ozkaynak", "net_kar", "gelir"],
    "SIGORTA": ["ozkaynak", "net_kar", "odenmis_sermaye"],
}

# Bu alanlar sadece ilgili formatta ANLAMLI. Tarama katmani bunu bilmeli.
ANLAMSIZ = {
    "BANKA":   ["net_borc_favok", "brut_kar", "satis_maliyeti", "favok"],
    "SIGORTA": ["net_borc_favok", "brut_kar", "satis_maliyeti", "favok"],
    "SANAYI":  [],
}


# ---------------------------------------------------------------- arama

def _indeks(veri):
    """{sadelestirilmis_ad: degerler} sozlugu. Ayni ad birden fazlaysa ilki kalir."""
    ix = {}
    for k in veri.get("kalemler", []):
        a = _sadelestir(k.get("ad", ""))
        if a and a not in ix:
            ix[a] = k.get("degerler", {})
    return ix


def kalem_bul(veri, alan, fmt=None, _ix=None):
    """
    Kanonik alan adini (ornegin 'ozkaynak') o sirketin formatindaki gercek
    kaleme cevirir ve deger sozlugunu doner. Bulamazsa None.
    """
    fmt = fmt or format_belirle(veri)
    adaylar = HARITA.get(fmt, {}).get(alan)
    if not adaylar:
        return None
    ix = _ix if _ix is not None else _indeks(veri)
    for aday in adaylar:
        d = ix.get(_sadelestir(aday))
        if d:
            return d
    return None


def tum_alanlar(veri, fmt=None):
    """Bir sirketin butun kanonik alanlarini tek gecisde cozer. {alan: degerler|None}"""
    fmt = fmt or format_belirle(veri)
    ix = _indeks(veri)
    return {alan: kalem_bul(veri, alan, fmt, _ix=ix) for alan in HARITA.get(fmt, {})}


# ---------------------------------------------------------------- coklu gecis

TOPLANACAK = {"finansal_borc"}   # tabloda birden fazla kez gecen ve TOPLANMASI gereken alanlar


def _indeks_coklu(veri):
    """{sadelestirilmis_ad: [degerler, degerler, ...]} - butun gecisler."""
    ix = {}
    for k in veri.get("kalemler", []):
        a = _sadelestir(k.get("ad", ""))
        if a:
            ix.setdefault(a, []).append(k.get("degerler", {}))
    return ix


def kalem_topla(veri, alan, donem, fmt=None, _ixc=None):
    """
    Bir alanin BUTUN gecislerini toplar ve tek bir donem degeri dondurur.
    "Finansal Borclar" gibi kisa+uzun vadeli olarak iki kez gecen kalemler
    icin kullanilir. Hicbir gecis bulunamazsa None doner.
    """
    fmt = fmt or format_belirle(veri)
    adaylar = HARITA.get(fmt, {}).get(alan) or []
    ixc = _ixc if _ixc is not None else _indeks_coklu(veri)
    toplam, bulundu = 0.0, False
    for aday in adaylar:
        for d in ixc.get(_sadelestir(aday), []):
            v = d.get(donem)
            if v is not None:
                toplam += float(v)
                bulundu = True
        if bulundu:
            break          # ilk eslesen ad ailesinin TUM gecisleri toplandi
    return toplam if bulundu else None


def deger(veri, alan, donem, fmt=None, _ix=None, _ixc=None):
    """Tek noktadan deger okuma. Toplanmasi gereken alanlarda otomatik toplar."""
    if alan in TOPLANACAK:
        return kalem_topla(veri, alan, donem, fmt, _ixc)
    d = kalem_bul(veri, alan, fmt, _ix)
    return None if d is None else d.get(donem)
