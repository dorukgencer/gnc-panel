// Bu fonksiyon Netlify'in kendi sunucusunda calisir (tarayicida degil).
// Bu yuzden FRED'e giden istek CORS'a takilmaz - sunucudan sunucuya konusma,
// tarayici kisitlamasi burada gecerli degil. Node'un yerlesik https modulu
// kullaniliyor, hicbir npm paketi kurulumuna gerek yok.
//
// API KEY: Netlify environment variable'dan okunur (FRED_API_KEY).
// Netlify dashboard -> Site settings -> Environment variables -> ekle.
// Koda ASLA yazilmaz.

const https = require('https');

// Panelin kullandigi seriler disinda baskasinin bu fonksiyonu genel FRED
// proxy'si olarak kullanmasini engellemek icin whitelist.
const IZINLI_SERILER = new Set([
  // Panelde kullanilan FRED serilerini buraya ekle, ornek:
  // 'VIXCLS', 'DXY', 'DFII10', 'BAMLH0A0HYM2'
]);

function getJson(url) {
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      let body = '';
      res.on('data', (chunk) => (body += chunk));
      res.on('end', () => {
        if (res.statusCode < 200 || res.statusCode >= 300) {
          reject(new Error('FRED HTTP ' + res.statusCode + ': ' + body.slice(0, 200)));
          return;
        }
        try {
          resolve(JSON.parse(body));
        } catch (e) {
          reject(new Error('FRED yaniti JSON degil: ' + body.slice(0, 200)));
        }
      });
    }).on('error', (err) => reject(err));
  });
}

exports.handler = async function (event) {
  const headers = {
    'Access-Control-Allow-Origin': '*',
    'Content-Type': 'application/json',
  };

  const apiKey = process.env.FRED_API_KEY;
  if (!apiKey) {
    return { statusCode: 500, headers, body: JSON.stringify({ error: 'FRED_API_KEY tanimli degil (Netlify env variable eksik)' }) };
  }

  const seriesId = event.queryStringParameters && event.queryStringParameters.series_id;
  if (!seriesId) {
    return { statusCode: 400, headers, body: JSON.stringify({ error: 'series_id parametresi eksik' }) };
  }

  // Whitelist bossa (henuz doldurulmadiysa) kontrolu atla; doldurulunca aktif olur.
  if (IZINLI_SERILER.size > 0 && !IZINLI_SERILER.has(seriesId)) {
    return { statusCode: 403, headers, body: JSON.stringify({ error: 'Bu seri izinli listede degil' }) };
  }

  const url = `https://api.stlouisfed.org/fred/series/observations?series_id=${encodeURIComponent(seriesId)}&api_key=${apiKey}&file_type=json&sort_order=desc&limit=25`;

  try {
    const data = await getJson(url);
    return { statusCode: 200, headers, body: JSON.stringify(data) };
  } catch (err) {
    return { statusCode: 500, headers, body: JSON.stringify({ error: (err && err.message) || 'bilinmeyen sunucu hatasi' }) };
  }
};
