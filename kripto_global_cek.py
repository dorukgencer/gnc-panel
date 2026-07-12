# -*- coding: utf-8 -*-
"""
GNC Insight - Kripto Global Metrikleri (BTC Dominans, Toplam Piyasa Degeri)
CoinGecko'nun ucretsiz /api/v3/global endpoint'inden ceker. API key gerekmez.

DIKKAT: CoinGecko'nun DOKUMANTASYONUNDAN yanit yapisinin genel hatlarini
biliyorum (data.market_cap_percentage.btc, data.total_market_cap.usd) ama
CANLI olarak dogrulayamadim (sandbox'ta CoinGecko'ya erisim yok). Bu yuzden
script SAVUNMACI yazildi: beklenen alan yolu bulunamazsa, GELEN HAM JSON'UN
TAMAMINI loglar - boylece ilk calistirmada yapı farkliysa hemen goruruz,
sessizce yanlis/bos veri yazmayiz (TCMB faizinde ogrendigimiz dersle ayni).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import requests

KLASOR = Path(__file__).parent
HEDEF = KLASOR / "gnc-panel" / "kripto_global.json"
URL = "https://api.coingecko.com/api/v3/global"


def main():
    try:
        r = requests.get(URL, timeout=20, headers={"Accept": "application/json"})
        r.raise_for_status()
        ham = r.json()
    except Exception as e:
        raise SystemExit(f"CoinGecko'ya erisilemedi: {e}")

    data = ham.get("data")
    if not data:
        print("[TESHIS] 'data' anahtari bulunamadi. Ham yanit:")
        print(json.dumps(ham, ensure_ascii=False, indent=2)[:2000])
        raise SystemExit("Beklenen yapi yok, dosya yazilmadi.")

    btc_dominans = None
    toplam_pd_usd = None

    mcp = data.get("market_cap_percentage")
    if isinstance(mcp, dict):
        btc_dominans = mcp.get("btc")

    tmc = data.get("total_market_cap")
    if isinstance(tmc, dict):
        toplam_pd_usd = tmc.get("usd")

    if btc_dominans is None or toplam_pd_usd is None:
        print("[TESHIS] Beklenen alanlar (market_cap_percentage.btc / total_market_cap.usd) bulunamadi.")
        print("Gelen 'data' objesinin ANAHTARLARI:", list(data.keys()))
        print("Ham 'data' icerigi (ilk 2000 karakter):")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
        if btc_dominans is None and toplam_pd_usd is None:
            raise SystemExit("Hicbir deger cikarilamadi, dosya yazilmadi.")

    cikti = {
        "guncelleme": datetime.now(timezone.utc).isoformat(),
        "kaynak": "CoinGecko (canli)",
        "btc_dominans_yuzde": round(btc_dominans, 2) if btc_dominans is not None else None,
        "toplam_piyasa_degeri_usd": toplam_pd_usd,
        "toplam_piyasa_degeri_trilyon_usd": round(toplam_pd_usd / 1_000_000_000_000, 3) if toplam_pd_usd else None,
    }
    HEDEF.write_text(json.dumps(cikti, ensure_ascii=False), encoding="utf-8")
    print(f"BTC dominans: %{cikti['btc_dominans_yuzde']}, Toplam PD: ${cikti['toplam_piyasa_degeri_trilyon_usd']} Tr")
    print(f"Tamamlandi -> {HEDEF}")
    print("[KONTROL] BTC dominansi genelde %40-60 araliginda olur, toplam PD $1.5-4 Tr araliginda olur. Cok farkliysa bildir.")


if __name__ == "__main__":
    main()
