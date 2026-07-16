// GNC Insight - Veri Proxy Fonksiyonu
// Panelin JSON verilerini PRIVATE GitHub repodan sunucu tarafinda ceker ve
// tarayiciya servis eder. Boylece:
//  1) Veri hicbir zaman public/acik bir yerde durmaz (GITHUB_TOKEN sadece
//     Netlify sunucusunda calisir, tarayiciya asla gitmez).
//  2) Actions'in attigi veri commit'leri Netlify deploy TETIKLEMEZ
//     (netlify.toml'daki ignore script sayesinde) - kredi yenmez.
//  3) Panel her zaman en TAZE veriyi gorur (bu fonksiyon her istekte
//     GitHub'dan taze cekiyor, kisa sureli cache disinda bekleme yok).
//
// GEREKLI: Netlify env variable GITHUB_TOKEN (fine-grained PAT,
// sadece bu repo, sadece "Contents: Read" yetkisiyle olusturulmali).

const https = require('https');

const REPO_SAHIP = 'dorukgencer';
const REPO_AD = 'gnc-panel';
const BRANCH = 'main';

// Sadece bu klasor altindaki dosyalara izin ver (path traversal / repo'nun
// baska dosyalarina erisimi engellemek icin).
const IZINLI_ONEK = 'gnc-panel/';

function githubdanCek(dosyaYolu, token) {
  return new Promise((resolve, reject) => {
    const url = `https://raw.githubusercontent.com/${REPO_SAHIP}/${REPO_AD}/${BRANCH}/${encodeURI(dosyaYolu)}`;
    const opts = {
      headers: {
        'Authorization': `token ${token}`,
        'User-Agent': 'gnc-panel-veri-proxy',
      },
    };
    https.get(url, opts, (res) => {
      let body = '';
      res.on('data', (c) => (body += c));
      res.on('end', () => {
        if (res.statusCode < 200 || res.statusCode >= 300) {
          reject(new Error(`GitHub HTTP ${res.statusCode}`));
          return;
        }
        resolve(body);
      });
    }).on('error', reject);
  });
}

exports.handler = async function (event) {
  const headers = {
    'Access-Control-Allow-Origin': '*',
    'Content-Type': 'application/json',
    // Kisa cache: tarayici 60 sn icinde ayni dosyayi tekrar isterse GitHub'a
    // gitmez, ama veri her zaman yakin zamanda taze kalir.
    'Cache-Control': 'public, max-age=60',
  };

  const token = process.env.GITHUB_TOKEN;
  if (!token) {
    return { statusCode: 500, headers, body: JSON.stringify({ error: 'GITHUB_TOKEN tanimli degil (Netlify env variable eksik)' }) };
  }

  const dosya = event.queryStringParameters && event.queryStringParameters.dosya;
  if (!dosya) {
    return { statusCode: 400, headers, body: JSON.stringify({ error: 'dosya parametresi eksik' }) };
  }

  // Guvenlik: sadece gnc-panel/ altindaki .json dosyalarina izin ver,
  // ".." gibi path traversal denemelerini REDDET (sessizce temizleme).
  if (dosya.includes('..') || !dosya.endsWith('.json') || dosya.startsWith('/')) {
    return { statusCode: 400, headers, body: JSON.stringify({ error: 'gecersiz dosya' }) };
  }
  const tamYol = IZINLI_ONEK + dosya;

  try {
    const icerik = await githubdanCek(tamYol, token);
    return { statusCode: 200, headers, body: icerik };
  } catch (err) {
    return { statusCode: 502, headers, body: JSON.stringify({ error: (err && err.message) || 'veri cekilemedi' }) };
  }
};
