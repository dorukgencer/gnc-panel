// GNC Insight - Kuresel Gostergeler (DXY, VIX, Nasdaq, US10Y) - CANLI
// Bu fonksiyon sektor.js ile AYNI mantigi (Yahoo Finance cerez+crumb) kullanir
// ama FARKLI bir amaca hizmet eder: FRED'deki bu seriler kaynaginda GUNDE
// BIR guncellendigi icin (ne kadar sik cekersek cekelim ayni bayat veriyi
// aliriz), bu dorduyu panel her acildiginda YENIDEN, o an CANLI cekeriz.
// Boylece "DXY 1 saat once, BIST 10 dakika once, US10Y 6 saat once" gibi
// parca parca bayatlik hissi ortadan kalkar - bu 4 gosterge HER ZAMAN
// "az once" olur (Yahoo'nun kendi gecikmesi disinda, genelde 15 dk).
//
// TR10Y burada YOK: Turkiye 10 yillik tahvil getirisi icin guvenilir,
// ucretsiz, gunluk-otesi bir Yahoo ticker'i yok. O yuzden TR10Y hala
// FRED'in gunluk pipeline'inda (makro_cek.py) kaliyor - bu bilinen ve
// kabul edilen bir istisna, gizlenmiyor.

const https = require('https');
const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36';

const GOSTERGELER = [
  { anahtar: 'dxy',    sembol: 'DX-Y.NYB', ad: 'Dolar Endeksi (DXY)', birim: 'endeks', bolen: 1 },
  { anahtar: 'vix',    sembol: '^VIX',     ad: 'VIX (Volatilite)',    birim: 'endeks', bolen: 1 },
  { anahtar: 'nasdaq', sembol: '^IXIC',    ad: 'Nasdaq Composite',   birim: 'endeks', bolen: 1 },
  { anahtar: 'us10y',  sembol: '^TNX',     ad: 'ABD 10Y Tahvil',      birim: '%',      bolen: 10 }, // Yahoo bunu x10 verir
];

function bekle(ms) { return new Promise((r) => setTimeout(r, ms)); }

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

async function gostergeCek(g, kimlik) {
  let url = 'https://query1.finance.yahoo.com/v8/finance/chart/'
    + encodeURIComponent(g.sembol) + '?range=5d&interval=1d';
  if (kimlik.crumb) url += '&crumb=' + encodeURIComponent(kimlik.crumb);
  const headers = kimlik.cookie ? { Cookie: kimlik.cookie } : {};

  for (let deneme = 0; deneme < 3; deneme++) {
    try {
      const r = await rawGet(url, headers);
      if (r.statusCode < 200 || r.statusCode >= 300) throw new Error('HTTP ' + r.statusCode);
      const data = JSON.parse(r.body);
      const res = data && data.chart && data.chart.result && data.chart.result[0];
      if (!res) throw new Error('bos');
      const kapanis = res.indicators.quote[0].close.filter((v) => v !== null);
      if (kapanis.length < 2) throw new Error('yetersiz veri');
      const son = kapanis[kapanis.length - 1] / g.bolen;
      const onceki = kapanis[kapanis.length - 2] / g.bolen;
      const degisim = onceki ? Math.round(((son / onceki - 1) * 100) * 100) / 100 : null;
      return {
        anahtar: g.anahtar, ad: g.ad, birim: g.birim,
        son: Math.round(son * 100) / 100,
        degisim_yuzde: degisim,
      };
    } catch (err) {
      if (deneme < 2) { await bekle(400 * (deneme + 1)); continue; }
    }
  }
  return { anahtar: g.anahtar, ad: g.ad, birim: g.birim, son: null, degisim_yuzde: null, hata: true };
}

exports.handler = async function () {
  const headers = {
    'Access-Control-Allow-Origin': '*',
    'Content-Type': 'application/json',
    // Kisa cache: ayni 60 saniye icinde tekrar istek gelirse Yahoo'ya
    // gitmeden onceki sonucu tekrar kullan (asiri istek atmayi onler).
    'Cache-Control': 'public, max-age=60',
  };

  try {
    const kimlik = await kimlikAl();
    const sonuclar = {};
    for (const g of GOSTERGELER) {
      sonuclar[g.anahtar] = await gostergeCek(g, kimlik);
      await bekle(200); // Yahoo'yu art arda hizli yagmurlamamak icin kucuk bosluk
    }
    return {
      statusCode: 200,
      headers,
      body: JSON.stringify({
        guncelleme: new Date().toISOString(),
        kaynak: 'Yahoo Finance (canli)',
        not: 'Bu veriler her istek aninda taze cekilir, onceden depolanmaz. TR10Y burada yok, FRED gunluk pipeline\'inda.',
        gostergeler: sonuclar,
      }),
    };
  } catch (err) {
    return { statusCode: 500, headers, body: JSON.stringify({ error: (err && err.message) || 'bilinmeyen hata' }) };
  }
};
