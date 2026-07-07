// Bu fonksiyon Netlify'in kendi sunucusunda calisir (tarayicida degil), bu yuzden
// Yahoo Finance'e giden istekler CORS'a takilmaz. Tum BIST sektor endekslerini
// (XBANK, XKMYA, XELKT ...) ve XU100'u ceker, her biri icin 1G/1H/1A/3A/Yilbasi
// getirilerini ve XU100'e gore rolatif performansi hesaplayip tek JSON doner.
// Not: Her endeks ilgili sektorun TAMAMINI kapsar (resmi BIST endeksi).

const https = require('https');

// Takip edilen endeksler. tip: referans / ana_grup / sektor
const ENDEKSLER = [
  { kod: 'XU100', ad: 'BIST 100', tip: 'referans' },
  { kod: 'XUSIN', ad: 'Sinai', tip: 'ana_grup' },
  { kod: 'XUMAL', ad: 'Mali', tip: 'ana_grup' },
  { kod: 'XUHIZ', ad: 'Hizmetler', tip: 'ana_grup' },
  { kod: 'XUTEK', ad: 'Teknoloji', tip: 'ana_grup' },
  { kod: 'XBANK', ad: 'Bankacilik', tip: 'sektor' },
  { kod: 'XSGRT', ad: 'Sigorta', tip: 'sektor' },
  { kod: 'XFINK', ad: 'Fin. Kiralama Faktoring', tip: 'sektor' },
  { kod: 'XHOLD', ad: 'Holding ve Yatirim', tip: 'sektor' },
  { kod: 'XGYO', ad: 'Gayrimenkul Yat. Ort.', tip: 'sektor' },
  { kod: 'XYORT', ad: 'Menkul Kiymet Yat. Ort.', tip: 'sektor' },
  { kod: 'XGIDA', ad: 'Gida ve Icecek', tip: 'sektor' },
  { kod: 'XKMYA', ad: 'Kimya Petrol Plastik', tip: 'sektor' },
  { kod: 'XMANA', ad: 'Metal Ana Sanayi', tip: 'sektor' },
  { kod: 'XMESY', ad: 'Metal Esya Makina', tip: 'sektor' },
  { kod: 'XTAST', ad: 'Tas Toprak (Cam Cimento)', tip: 'sektor' },
  { kod: 'XTEKS', ad: 'Tekstil ve Deri', tip: 'sektor' },
  { kod: 'XKAGT', ad: 'Orman Kagit Basim', tip: 'sektor' },
  { kod: 'XELKT', ad: 'Elektrik', tip: 'sektor' },
  { kod: 'XILTM', ad: 'Iletisim', tip: 'sektor' },
  { kod: 'XULAS', ad: 'Ulastirma', tip: 'sektor' },
  { kod: 'XTCRT', ad: 'Ticaret', tip: 'sektor' },
  { kod: 'XTRZM', ad: 'Turizm', tip: 'sektor' },
  { kod: 'XINSA', ad: 'Insaat ve Bayindirlik', tip: 'sektor' },
  { kod: 'XMADN', ad: 'Madencilik', tip: 'sektor' },
  { kod: 'XBLSM', ad: 'Bilisim', tip: 'sektor' },
  { kod: 'XSPOR', ad: 'Spor', tip: 'sektor' },
];

function getJson(url) {
  return new Promise((resolve, reject) => {
    const opts = { headers: { 'User-Agent': 'Mozilla/5.0 (compatible; GncInsightBot/1.0)' } };
    https.get(url, opts, (res) => {
      let body = '';
      res.on('data', (chunk) => (body += chunk));
      res.on('end', () => {
        if (res.statusCode < 200 || res.statusCode >= 300) {
          reject(new Error('Yahoo HTTP ' + res.statusCode));
          return;
        }
        try { resolve(JSON.parse(body)); }
        catch (e) { reject(new Error('Yahoo yaniti JSON degil')); }
      });
    }).on('error', (err) => reject(err));
  });
}

function yuzde(son, onceki) {
  if (son == null || onceki == null || onceki === 0) return null;
  return Math.round((son / onceki - 1) * 1000) / 10;
}

// Kapanis serisinden getirileri hesaplar
function getiriHesapla(kapanislar, tarihler) {
  const c = [];
  const t = [];
  for (let i = 0; i < kapanislar.length; i++) {
    if (kapanislar[i] != null) { c.push(kapanislar[i]); t.push(tarihler[i]); }
  }
  if (c.length < 2) return {};
  const son = c[c.length - 1];
  const geri = (n) => c.length > n ? c[c.length - 1 - n] : null;

  // Yilbasindan bu yana: bu yilin ilk kapanisi
  const sonYil = new Date(t[t.length - 1] * 1000).getUTCFullYear();
  let ilkBuYil = null;
  for (let i = 0; i < t.length; i++) {
    if (new Date(t[i] * 1000).getUTCFullYear() === sonYil) { ilkBuYil = c[i]; break; }
  }

  return {
    son_deger: Math.round(son * 100) / 100,
    g1: yuzde(son, geri(1)),
    h1: yuzde(son, geri(5)),
    a1: yuzde(son, geri(21)),
    a3: yuzde(son, geri(63)),
    ybb: yuzde(son, ilkBuYil),
  };
}

async function endeksCek(e) {
  const url = 'https://query1.finance.yahoo.com/v8/finance/chart/'
    + e.kod + '.IS?range=1y&interval=1d';
  try {
    const data = await getJson(url);
    const r = data && data.chart && data.chart.result && data.chart.result[0];
    if (!r) throw new Error('bos');
    const kapanis = r.indicators.quote[0].close;
    const tarih = r.timestamp;
    const g = getiriHesapla(kapanis, tarih);
    if (!g.son_deger) throw new Error('veri yok');
    return Object.assign({}, e, g);
  } catch (err) {
    return Object.assign({}, e, { son_deger: null, g1: null, h1: null, a1: null, a3: null, ybb: null, hata: true });
  }
}

exports.handler = async function () {
  const headers = {
    'Access-Control-Allow-Origin': '*',
    'Content-Type': 'application/json',
    'Cache-Control': 'public, max-age=900', // 15 dk tarayici/CDN onbellegi
  };

  try {
    // Tumunu paralel cek
    const sonuclar = await Promise.all(ENDEKSLER.map(endeksCek));

    // XU100'e gore rolatif
    const xu = sonuclar.find((s) => s.kod === 'XU100');
    const donemler = ['g1', 'h1', 'a1', 'a3', 'ybb'];
    for (const s of sonuclar) {
      for (const d of donemler) {
        if (xu && s[d] != null && xu[d] != null) {
          s['rol_' + d] = Math.round((s[d] - xu[d]) * 10) / 10;
        } else {
          s['rol_' + d] = null;
        }
      }
    }

    return {
      statusCode: 200,
      headers,
      body: JSON.stringify({
        guncelleme: new Date().toISOString(),
        endeksler: sonuclar,
      }),
    };
  } catch (err) {
    return { statusCode: 500, headers, body: JSON.stringify({ error: (err && err.message) || 'bilinmeyen hata' }) };
  }
};
