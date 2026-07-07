// Bu fonksiyon Netlify'in kendi sunucusunda calisir (tarayicida degil), bu yuzden
// Yahoo Finance'e giden istekler CORS'a takilmaz. Tum BIST sektor endekslerini
// (XBANK, XKMYA, XELKT ...) ve XU100'u ceker, her biri icin 1G/1H/1A/3A/Yilbasi
// getirilerini ve XU100'e gore rolatif performansi hesaplayip tek JSON doner.
//
// ONEMLI: Yahoo son donemde sunucu isteklerinde cerez + crumb (kimlik anahtari)
// istiyor. Fonksiyon once bunlari alir, sonra tum istekleri bunlarla yapar.

const https = require('https');
const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36';

const ENDEKSLER = [
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

function bekle(ms) { return new Promise((r) => setTimeout(r, ms)); }

// Ham GET: statusCode + headers + body doner, 2xx olmasa da reject etmez
function rawGet(url, ekHeaders) {
  return new Promise((resolve, reject) => {
    const opts = { headers: Object.assign({ 'User-Agent': UA, 'Accept': '*/*' }, ekHeaders || {}) };
    https.get(url, opts, (res) => {
      let body = '';
      res.on('data', (c) => (body += c));
      res.on('end', () => resolve({ statusCode: res.statusCode, headers: res.headers, body }));
    }).on('error', reject);
  });
}

// Cerez + crumb al (bir kez)
async function kimlikAl() {
  let cookie = '';
  try {
    const r = await rawGet('https://fc.yahoo.com/');
    const sc = r.headers['set-cookie'];
    if (sc && sc.length) cookie = sc.map((c) => c.split(';')[0]).join('; ');
  } catch (e) { /* cerez alinamadi, crumbsuz denenecek */ }

  let crumb = '';
  try {
    const r2 = await rawGet('https://query1.finance.yahoo.com/v1/test/getcrumb',
      cookie ? { Cookie: cookie } : {});
    if (r2.statusCode === 200 && r2.body && r2.body.indexOf('<') === -1) {
      crumb = r2.body.trim();
    }
  } catch (e) { /* crumb alinamadi */ }

  return { cookie, crumb };
}

function yuzde(son, onceki) {
  if (son == null || onceki == null || onceki === 0) return null;
  return Math.round((son / onceki - 1) * 1000) / 10;
}

function getiriHesapla(kapanislar, tarihler) {
  const c = [];
  const t = [];
  for (let i = 0; i < kapanislar.length; i++) {
    if (kapanislar[i] != null) { c.push(kapanislar[i]); t.push(tarihler[i]); }
  }
  if (c.length < 2) return {};
  const son = c[c.length - 1];
  const geri = (n) => c.length > n ? c[c.length - 1 - n] : null;

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

async function endeksCek(e, kimlik) {
  let url = 'https://query1.finance.yahoo.com/v8/finance/chart/'
    + e.kod + '.IS?range=1y&interval=1d';
  if (kimlik.crumb) url += '&crumb=' + encodeURIComponent(kimlik.crumb);
  const headers = kimlik.cookie ? { Cookie: kimlik.cookie } : {};

  for (let deneme = 0; deneme < 3; deneme++) {
    try {
      const r = await rawGet(url, headers);
      if (r.statusCode < 200 || r.statusCode >= 300) throw new Error('HTTP ' + r.statusCode);
      const data = JSON.parse(r.body);
      const res = data && data.chart && data.chart.result && data.chart.result[0];
      if (!res) throw new Error('bos');
      const kapanis = res.indicators.quote[0].close;
      const tarih = res.timestamp;
      const g = getiriHesapla(kapanis, tarih);
      if (!g.son_deger) throw new Error('veri yok');
      return Object.assign({}, e, g);
    } catch (err) {
      if (deneme < 2) { await bekle(400 * (deneme + 1)); continue; }
    }
  }
  return Object.assign({}, e, { son_deger: null, g1: null, h1: null, a1: null, a3: null, ybb: null, hata: true });
}

exports.handler = async function () {
  const headers = {
    'Access-Control-Allow-Origin': '*',
    'Content-Type': 'application/json',
    'Cache-Control': 'public, max-age=900',
  };

  try {
    const kimlik = await kimlikAl();

    // 4'erli gruplar halinde cek
    const sonuclar = [];
    for (let i = 0; i < ENDEKSLER.length; i += 4) {
      const grup = ENDEKSLER.slice(i, i + 4);
      const grupSonuc = await Promise.all(grup.map((e) => endeksCek(e, kimlik)));
      sonuclar.push(...grupSonuc);
      if (i + 4 < ENDEKSLER.length) await bekle(250);
    }

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
        crumb_var: !!kimlik.crumb,
        endeksler: sonuclar,
      }),
    };
  } catch (err) {
    return { statusCode: 500, headers, body: JSON.stringify({ error: (err && err.message) || 'bilinmeyen hata' }) };
  }
};
