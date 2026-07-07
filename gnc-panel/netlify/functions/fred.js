// Bu fonksiyon Netlify'in kendi sunucusunda calisir (tarayicida degil).
// Bu yuzden FRED'e giden istek CORS'a takilmaz - sunucudan sunucuya konusma,
// tarayici kisitlamasi burada gecerli degil. Node'un yerlesik https modulu
// kullaniliyor, hicbir npm paketi kurulumuna gerek yok.

const https = require('https');

const FRED_API_KEY = 'bdd9fbd79b3af93b3f2889637eb27c7e';

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

  const seriesId = event.queryStringParameters && event.queryStringParameters.series_id;
  if (!seriesId) {
    return { statusCode: 400, headers, body: JSON.stringify({ error: 'series_id parametresi eksik' }) };
  }

  const url = `https://api.stlouisfed.org/fred/series/observations?series_id=${encodeURIComponent(seriesId)}&api_key=${FRED_API_KEY}&file_type=json&sort_order=desc&limit=6`;

  try {
    const data = await getJson(url);
    return { statusCode: 200, headers, body: JSON.stringify(data) };
  } catch (err) {
    return { statusCode: 500, headers, body: JSON.stringify({ error: (err && err.message) || 'bilinmeyen sunucu hatasi' }) };
  }
};
