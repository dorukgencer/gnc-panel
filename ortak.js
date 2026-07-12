/* ============================================================
   GNC Insight — Ortak JS
   Her sayfa bu dosyayi <script> ile ceker. Sidebar olusturma,
   veri proxy fetch yardimcisi, ortak grafik fonksiyonlari burada.
   ============================================================ */

const GNC_NAV = [
  { id: "genel-bakis",       ikon: "🏠", ad: "Genel Bakış",        href: "index.html" },
  { id: "ortam-modelleme",   ikon: "◈",  ad: "Ortam Modelleme",    href: "ortam-modelleme.html" },
  { id: "sektor-rotasyonu",  ikon: "◐",  ad: "Sektör Rotasyonu",   href: "sektor-rotasyonu.html" },
  { id: "makro-ortam",       ikon: "▤",  ad: "Makro Ortam",        href: "makro-ortam.html" },
  { id: "kripto-ortam",      ikon: "◇",  ad: "Kripto Ortamı",      href: "kripto-ortam.html" },
  { id: "bist-gorunumu",     ikon: "▥",  ad: "BIST Görünümü",      href: "bist-gorunumu.html" },
  { id: "haftalik-raporlar", ikon: "▦",  ad: "Haftalık Raporlar",  href: "raporlar.html" },
  { id: "makro-takvim",      ikon: "▧",  ad: "Makro Takvim",       href: "takvim.html" },
];

/**
 * Sidebar'i olusturur ve verilen elemente basar.
 * aktifId: GNC_NAV icindeki hangi id'nin aktif (vurgulu) gorunecegi.
 */
function gncSidebarOlustur(aktifId, hedefElementId) {
  const el = document.getElementById(hedefElementId);
  if (!el) return;
  const linkler = GNC_NAV.map(item => {
    const aktifSinif = item.id === aktifId ? " active" : "";
    return `<a class="gnc-nav-item${aktifSinif}" href="${item.href}">
      <span class="ikon">${item.ikon}</span><span>${item.ad}</span>
    </a>`;
  }).join("");
  el.innerHTML = `
    <div class="gnc-logo">GNC <span>Insight</span></div>
    <nav class="gnc-nav">${linkler}</nav>
  `;
}

/**
 * Netlify proxy uzerinden gnc-panel/*.json dosyasi ceker.
 * Basarisiz olursa null doner (throw etmez) - cagiran taraf
 * kendi "veri yok" mesajini gostermekten sorumlu.
 */
async function gncVeriCek(dosyaYolu) {
  try {
    const res = await fetch('/.netlify/functions/veri?dosya=' + encodeURIComponent(dosyaYolu) + '&t=' + Date.now());
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    return null;
  }
}

/** Sayi formatlama: +/- isaretli yuzde. */
function gncYuzde(v, ondalik) {
  if (v === null || v === undefined || isNaN(v)) return "—";
  ondalik = ondalik === undefined ? 1 : ondalik;
  return (v >= 0 ? "+" : "") + v.toFixed(ondalik) + "%";
}

/** Pozitif/negatif deger icin CSS sinifi. */
function gncYon(v) {
  if (v === null || v === undefined || isNaN(v)) return "";
  return v >= 0 ? "yon-pozitif" : "yon-negatif";
}

/** Buyuk sayilari kisaltir: 1234567 -> "1,23 Mn" gibi (TR bicimi, basit). */
function gncSayiKisalt(v) {
  if (v === null || v === undefined || isNaN(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e12) return (v / 1e12).toFixed(2).replace(".", ",") + " Tr";
  if (abs >= 1e9) return (v / 1e9).toFixed(2).replace(".", ",") + " Mr";
  if (abs >= 1e6) return (v / 1e6).toFixed(2).replace(".", ",") + " Mn";
  return v.toLocaleString("tr-TR");
}

/** Evre kodunu Turkce etikete cevirir. */
const GNC_EVRE_AD = {
  genisleme: "Genişleme",
  toparlanma: "Toparlanma",
  yavaslama: "Yavaşlama",
  daralma: "Daralma",
};

/** Evre chip HTML'i uretir. */
function gncEvreChip(evreKod) {
  const ad = GNC_EVRE_AD[evreKod] || evreKod;
  return `<span class="evre-chip ${evreKod}">${ad}</span>`;
}

/** Tarihi "10 Tem" gibi kisa Turkce bicime cevirir. */
function gncTarihKisa(tarihStr) {
  const d = new Date(tarihStr);
  if (isNaN(d)) return tarihStr;
  return d.toLocaleDateString("tr-TR", { day: "numeric", month: "short" }).toUpperCase();
}
