# -*- coding: utf-8 -*-
"""
GNC Insight - BTC On-Chain Metrikleri (Coin Metrics Community API - ucretsiz)
MVRV, MVRV Z-Score, NUPL, Realized Price ve aktif adres verilerini ceker,
gnc-panel/onchain_veri.json'a yazar. API anahtari gerektirmez.
Kaynak: community-api.coinmetrics.io (Creative Commons)
"""

import json
import math
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

METRIKLER = ["CapMVRVCur", "CapRealUSD", "CapMrktCurUSD", "SplyCur", "AdrActCnt"]
BASE = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"


def cek():
    bas = (datetime.now() - timedelta(days=1300)).strftime("%Y-%m-%d")
    q = urllib.parse.urlencode({
        "assets": "btc",
        "metrics": ",".join(METRIKLER),
        "frequency": "1d",
        "start_time": bas,
        "page_size": "10000",
    })
    satirlar = []
    url = BASE + "?" + q
    basliklar = {"User-Agent": "Mozilla/5.0 (compatible; GNCInsightBot/1.0)", "Accept": "application/json"}
    for _ in range(3):  # sayfalama (gerekirse)
        req = urllib.request.Request(url, headers=basliklar)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        satirlar.extend(data.get("data", []))
        tok = data.get("next_page_token")
        if not tok:
            break
        url = BASE + "?" + q + "&next_page_token=" + urllib.parse.quote(tok)
    return satirlar


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def main():
    ham = cek()
    print(f"{len(ham)} gunluk kayit alindi")

    seri = []
    for r in ham:
        t = r.get("time", "")[:10]
        mkt = f(r.get("CapMrktCurUSD"))
        real = f(r.get("CapRealUSD"))
        sply = f(r.get("SplyCur"))
        mvrv = f(r.get("CapMVRVCur"))
        adr = f(r.get("AdrActCnt"))
        nupl = ((mkt - real) / mkt) if (mkt and real) else None
        rprice = (real / sply) if (real and sply) else None
        seri.append({"t": t, "mvrv": mvrv, "real": real, "mkt": mkt,
                     "nupl": nupl, "rprice": rprice, "adr": adr})

    # MVRV Z-Score = (mkt - real) / std(mkt)  [tum pencere std'si]
    mktler = [s["mkt"] for s in seri if s["mkt"] is not None]
    if len(mktler) > 2:
        ort = sum(mktler) / len(mktler)
        std = math.sqrt(sum((x - ort) ** 2 for x in mktler) / len(mktler))
        for s in seri:
            s["mvrvz"] = ((s["mkt"] - s["real"]) / std) if (s["mkt"] and s["real"] and std) else None
    else:
        for s in seri:
            s["mvrvz"] = None

    def son(anahtar):
        for s in reversed(seri):
            if s.get(anahtar) is not None:
                return s[anahtar]
        return None

    def gecmis(anahtar, n=180):
        return [{"t": s["t"], "v": round(s[anahtar], 4)} for s in seri[-n:] if s.get(anahtar) is not None]

    metrikler = [
        {"anahtar": "mvrv", "isim": "MVRV Oranı", "birim": "x",
         "yorum": "Piyasa değerinin gerçekleşen değere (aggregate maliyet bazına) oranı. 1'in altı tarihsel dip bölgesi, aşırı yüksek seviyeler tepe uyarısıdır. Tek başına değil, teyitle okunmalı.",
         "kaynak": "https://charts.checkonchain.com/btconchain/pricing/mvrv/mvrv_light.html"},
        {"anahtar": "mvrvz", "isim": "MVRV Z-Score", "birim": "",
         "yorum": "MVRV'nin uzun vadeli oynaklığa göre normalize edilmiş hali. Döngüler arası kıyas için daha nettir; aşırı yüksek/düşük Z bölgeleri tepe ve dipleri işaret eder.",
         "kaynak": "https://charts.checkonchain.com/btconchain/pricing/mvrv_zscore/mvrv_zscore_light.html"},
        {"anahtar": "nupl", "isim": "NUPL (Net Gerçekleşmemiş K/Z)", "birim": "",
         "yorum": "Dolaşımdaki coinlerin toplam gerçekleşmemiş kâr/zarar oranı. Pozitif = piyasa toplu kârda, negatif = zararda. Aşırı pozitif bölge açgözlülük, negatif bölge teslimiyet duygusudur.",
         "kaynak": "https://charts.checkonchain.com/btconchain/unrealised/nupl/nupl_light.html"},
        {"anahtar": "rprice", "isim": "Realized Price (Gerçekleşen Fiyat)", "birim": "$",
         "yorum": "Coinlerin son hareket ettiği fiyatların ortalaması; ağın toplam maliyet bazı. Fiyat bu seviyenin altına inince piyasa ortalama zararda demektir, tarihsel dip bölgeleri buralardır.",
         "kaynak": "https://charts.checkonchain.com/btconchain/pricing/realised_price/realised_price_light.html"},
        {"anahtar": "adr", "isim": "Aktif Adres Sayısı", "birim": "",
         "yorum": "Günlük ağda işlem yapan benzersiz adres sayısı; ağ kullanımının ve talebin göstergesi. Artan aktivite sağlıklı talep, düşen aktivite ilgi kaybı sinyali olabilir.",
         "kaynak": "https://charts.checkonchain.com/btconchain/network/addresses_active/addresses_active_light.html"},
    ]
    for m in metrikler:
        m["son"] = son(m["anahtar"])
        m["seri"] = gecmis(m["anahtar"])

    # Sadece link olarak sunulacak derin metrikler (ucretsiz API yok)
    linkler = [
        {"isim": "SOPR", "aciklama": "Harcanan coinlerin kâr/zarar oranı", "link": "https://charts.checkonchain.com/btconchain/sopr/sopr_7dma/sopr_7dma_light.html"},
        {"isim": "LTH vs STH", "aciklama": "Uzun/kısa vadeli sahip davranışı", "link": "https://charts.checkonchain.com/btconchain/lifespan/lth_sth_supply/lth_sth_supply_light.html"},
        {"isim": "HODL Dalgaları", "aciklama": "Coin yaşına göre arz dağılımı", "link": "https://charts.checkonchain.com/btconchain/lifespan/hodlwaves/hodlwaves_light.html"},
        {"isim": "CDD (90g MA)", "aciklama": "Yok edilen coin-gün", "link": "https://charts.checkonchain.com/btconchain/lifespan/cdd90_supplyadj/cdd90_supplyadj_light.html"},
        {"isim": "Funding & Open Interest", "aciklama": "Türev piyasa konumlanması", "link": "https://www.coinglass.com/FundingRate"},
    ]

    cikti = {"guncelleme": datetime.now().isoformat(), "kaynak": "Coin Metrics (Community)",
             "metrikler": metrikler, "linkler": linkler}
    hedef = Path(__file__).parent / "gnc-panel" / "onchain_veri.json"
    hedef.parent.mkdir(parents=True, exist_ok=True)
    hedef.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")
    gelen = sum(1 for m in metrikler if m["son"] is not None)
    print(f"Tamamlandi: {gelen}/{len(metrikler)} metrik -> {hedef}")


if __name__ == "__main__":
    main()
