/* ============================================================
   GNC Insight — Ortak JS
   Her sayfa bu dosyayi <script> ile ceker. Sidebar olusturma,
   veri proxy fetch yardimcisi, ortak grafik fonksiyonlari burada.
   ============================================================ */

const GNC_NAV_GRUPLARI = [
  { grup: "Genel", ogeler: [
    { id: "genel-bakis",      ad: "Genel Bakış",       href: "gnc_panel.html" },
    { id: "ortam-modelleme",  ad: "Ortam Modelleme",   href: "ortam-modelleme.html" },
    { id: "sektor-rotasyonu", ad: "Sektör Rotasyonu",  href: "sektor-rotasyonu.html" },
  ]},
  { grup: "Değerlendirme", ogeler: [
    { id: "makro-ortam",  ad: "Makro Ortam",   href: "makro-ortam.html" },
    { id: "kripto-ortam", ad: "Kripto Ortamı", href: "kripto-ortam.html" },
    { id: "bist-gorunumu", ad: "BIST Görünümü", href: "bist-gorunumu.html" },
  ]},
  { grup: "Araştırma", ogeler: [
    { id: "haftalik-raporlar", ad: "Haftalık Raporlar", href: "raporlar.html" },
    { id: "makro-takvim",      ad: "Makro Takvim",      href: "takvim.html" },
    { id: "arsiv",             ad: "Arşiv",             href: "arsiv.html" },
  ]},
  { grup: "Hesap", ogeler: [
    { id: "uyelik",  ad: "Üyelik",  href: "uyelik.html" },
    { id: "ayarlar", ad: "Ayarlar", href: "ayarlar.html" },
  ]},
];

/**
 * Sidebar'i olusturur (gruplu nav + marka + alt not, tasarim mockup'iyla birebir).
 * aktifId: hangi nav-item'in aktif gorunecegi.
 */
function gncSidebarOlustur(aktifId, hedefElementId) {
  const el = document.getElementById(hedefElementId);
  if (!el) return;
  let navHtml = "";
  GNC_NAV_GRUPLARI.forEach(grup => {
    navHtml += `<div class="nav-group">${grup.grup}</div>`;
    grup.ogeler.forEach(item => {
      const aktifSinif = item.id === aktifId ? " active" : "";
      navHtml += `<a class="nav-item${aktifSinif}" href="${item.href}">${item.ad}</a>`;
    });
  });
  el.innerHTML = `
    <div class="sidebar-brand">
      <div class="mark font-display">GNC Insight</div>
      <div class="sub">Ortam Paneli</div>
    </div>
    <nav class="nav-scroll">${navHtml}</nav>
    <div class="sidebar-foot">Bu panel <b>dönemsel</b> okuma içindir.<br>Her Pazartesi güncellenir.</div>
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

/** Bir elemana "Veri güncellenme: DD.MM.YYYY HH:MM" yazar. Kaynak dosya
 * yoksa/okunamiyorsa acikca belirtir - sessizce bos birakmaz. Tum sayfalar
 * (Genel Bakis + Sektor Rotasyonu) bu TEK fonksiyonu paylasir, boylece
 * "her veri icin ne zaman guncellendigi" tutarli sekilde gosterilir. */
function gncVeriZamani(elemanId, isoTarih) {
  const el = document.getElementById(elemanId);
  if (!el) return;
  if (!isoTarih) { el.textContent = "Veri zamanı bilinmiyor"; return; }
  try {
    const d = new Date(isoTarih);
    const gun = String(d.getDate()).padStart(2, '0');
    const ay = String(d.getMonth() + 1).padStart(2, '0');
    const saat = String(d.getHours()).padStart(2, '0');
    const dk = String(d.getMinutes()).padStart(2, '0');
    el.textContent = `Veri güncellenme: ${gun}.${ay}.${d.getFullYear()} ${saat}:${dk}`;
  } catch (e) { el.textContent = "Veri zamanı okunamadı"; }
}

/** Bir kart BIRDEN FAZLA kaynaktan besleniyorsa (orn. Turkiye Makro: faiz +
 * deflator + makro), bunlarin EN ESKISINI doner - kullaniciyi yaniltmamak
 * icin ("en taze" degil "en eski/en muhafazakar" gosterilir). Gecersiz/eksik
 * tarihler otomatik elenir. */
function gncEnEskiTarih(...isoTarihler) {
  const gecerli = isoTarihler.filter(t => t && !isNaN(new Date(t)));
  if (!gecerli.length) return null;
  return gecerli.reduce((enEski, t) => new Date(t) < new Date(enEski) ? t : enEski);
}

/** Tum sayfadaki (i) tooltip ikonlarini TIKLAMA ile ac/kapa (hover degil -
 * sartname "tiklaninca aciliyor" diyor, mobilde de calismasi icin sart).
 * Baska bir yere tiklaninca acik olan tooltip kapanir. */
document.addEventListener("click", (e) => {
  const tiklananIkon = e.target.closest(".gnc-info");
  document.querySelectorAll(".gnc-info.acik").forEach(ikon => {
    if (ikon !== tiklananIkon) ikon.classList.remove("acik");
  });
  if (tiklananIkon) {
    tiklananIkon.classList.toggle("acik");
    e.stopPropagation();
  }
});
