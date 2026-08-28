# GNC Panel — Sistem Güncellemesi (29 Ağustos 2026)

Bu paket **tam projedir**, yama değil. Doğrudan mevcut deponun üzerine açılabilir.

---

## ⚠ Önce bunu oku: depoyu public YAPMA

Public yapma kararını "sınırsız Actions dakikası" için vermiştin. İki sebeple
artık gereksiz — ve zararlı:

**1. Dakika sorunu zaten çözüldü.** Yeni iş akışı yapısıyla aylık tüketim
1.438 → ~980 dakika. 3.000 kotasının üçte biri. Sorun kalmadı.

**2. Kendi mimarin private repo üzerine kurulu.** `netlify/functions/veri.js`
dosyanı okudum, kendi yorumun şöyle diyor:

> *"Panelin JSON verilerini PRIVATE GitHub repodan sunucu tarafında çeker...
> Veri hiçbir zaman public/açık bir yerde durmaz."*

Depoyu public yaparsan bu proxy anlamsızlaşır — tüm veri
`raw.githubusercontent.com` üzerinden herkese açık olur. Üstelik **geri
alınamaz**: public geçmiş arşivlenir, sonradan private yapmak yayılmış veriyi
geri getirmez.

Sen "sonradan gizlemek mümkünse" diye sormuştun. Cevap: **mümkün, ve sen bunu
zaten inşa etmişsin.** Bozma.

`tarama.html` de aynı proxy'yi kullanacak şekilde yazıldı (yerel geliştirme
için doğrudan okuma yedeği var).

---

## Ne değişti

### Yeni: Tarama sayfası

Sistemin asıl amacı olan sayfa. 472 şirket → sırayla kapılar → **35 aday**.

Kapı yapısı (gerçek veriyle ölçülmüş sonuçlar):

| Kapı | Elenen | Kalan |
|---|---:|---:|
| Başlangıç | — | 472 |
| Format (banka + sigorta ayrı hatta) | 18 | 454 |
| Veri sağlığı (bayat + karantina) | 23 | 431 |
| Piyasa verisi eksik | 1 | 430 |
| Likidite (hacim + halka açıklık) | 43 | 387 |
| Ölçülebilirlik | 0 | 387 |
| Dayanıklılık (nakit akışı, tahakkuk, borç, faiz) | 274 | 113 |
| Değerleme (sektör içi en pahalı dilim) | 26 | 87 |
| Fiyat vetosu → **elemez, İZLEME'ye ayırır** | 52 | **35** |

Üç sekme: **Adaylar (35)** · **İzleme (52)** · **Elenenler (385)**.
Her kapıya tıklayınca kırılım açılır — hangi test kaç şirket düşürdü.
Her satıra tıklayınca şirketin bütün ölçüleri açılır.

### Tasarım ilkeleri (koda gömülü)

1. **Önce ele, sonra sırala.** Hangi hissenin kazanacağı bilinmiyor; hangi
   şirketin yapısal olarak riskli olduğu biliniyor.
2. **Mutlak eşik yok, kesitsel yüzdelik var.** "Net borç/FAVÖK < 3" benim
   tercihimdir; "sektöründe en borçlu %25" veriden gelir. Enflasyon muhasebesi
   mutlak eşikleri zaten anlamsız kıldı.
3. **Skor yok.** Tek sayıya indirgeme sahte kesinlik üretir.
4. **Eksik filtre gizlenmez.** VBTS tedbiri ve denetim görüşü verisi yok —
   sayfada açıkça "çalışmayan filtreler" olarak listeleniyor.
5. **Şüpheli veri kullanılmaz.** Karantinadaki şirket-yılları hesaba katılmaz.

### Tasarımın kendi kendine sınanması

Motoru yazdıktan sonra iki tur karşı argüman uygulandı. Beşi düzeltildi:

| İtiraz | Düzeltme |
|---|---|
| Dayanıklılık kapısı 274 eliyor, hangi test bilinmiyor | Kapı içi kırılım eklendi (faiz karşılama 207, nakit akışı 119, tahakkuk 96, borç 52, FAVÖK 46) |
| Bir şirket birden çok testten kalabilir, tek sebep kaydediliyordu | Tüm sebepler kaydediliyor |
| Fiyat vetosu bir kalite kuralı değil, zamanlama kuralı — elenenlerle aynı çöpe atılıyordu | **İzleme listesi** eklendi: kaliteyi geçmiş, zamanlaması bekleyen 52 şirket |
| Veto tek taraflıydı; ortalamanın çok üstündeki hisse de risklidir | "Uzamış" etiketi eklendi (%30 üstü) |
| 35 adaydan 12-15 slot nasıl seçilecek, tanımsız | Sektör dağılımı gösteriliyor — yığılma görünür oldu |

**Ayrıca bir sessiz hata bulundu ve düzeltildi:** değerleme filtresi, sektörde
8'den az şirket kalınca eşik üretemeyip **hiçbir uyarı vermeden** herkesi
geçiriyordu. 17 sektörün 10'u bu durumdaydı, 35 şirket filtresiz geçiyordu.
Artık evren eşiğine düşülüyor ve bu durum sayfada raporlanıyor.

### Menü temizliği

Menüde 12 bağlantı vardı, karşılığında 3 sayfa. **9 ölü link kaldırıldı.**
Sistem artık dört sayfa:

- **Genel Bakış** — ortam okuması
- **Sektör Rotasyonu** — ortamın sektör boyutu
- **Tarama** — eleme motoru *(yeni)*
- **Şirketler** — tek şirket derinlemesine

Yapılmayan sayfalar (`makro-ortam`, `takvim`, `raporlar`, `kripto-ortam`,
`bist-gorunumu`, `arsiv`, `uyelik`, `ayarlar`) menüden ve ana sayfadaki
"Detay →" bağlantılarından çıkarıldı.

### Sektör rotasyonu artık bir işe yarıyor

Şikâyetin "ne işe yaradığı belirsiz"di. Doğruydu — çıktı bir karara
bağlanmamıştı. İki bağlantı kuruldu:

1. Rotasyon sayfasında bir sektörün yanındaki **→** artık taramaya gidiyor,
   o sektörde **taramadan geçen** şirketleri gösteriyor.
2. Tarama sayfasında her adayın sektörünün rotasyon evresi etiketleniyor;
   "Daralma evresindekileri gizle" filtresi var.

Yani rotasyon artık "bilgi" değil, **eleme girdisi**.

### Bilanço verisi: 18 kritik hata → 0

Üç ayrı tablo formatı (SANAYİ 454 / BANKA 12 / SİGORTA 6) tanınmıyordu.
`kalem_haritasi.py` üçünü de çözüyor — **472/472 şirkette bütün zorunlu
kalemler bulunuyor**, katılım bankası ALBRK dahil.

"Brüt kâr tutmuyor" uyarıları da yanlıştı: finans segmenti olan holdinglerde
`BRÜT KAR = Ticari Brüt Kar + Finans Sektöründen Brüt Kar`. Düzeltildi.

Temiz 404 → **425**. Kalan gerçek sorun: 45 şirkette kümülatif seri bozuk
(`karantina.json`) — bu ihlaller 2017-2025'e eşit dağılmış, yani enflasyon
muhasebesi kaynaklı değil, kaynak veri sorunu.

### Dolar endeksi

Sorun etiket değil **değerdi**. Panel `DTWEXBGS` gösteriyor — FED'in 26 para
birimli geniş endeksi (2006=100), ~120 seviyesinde. ICE DXY ~97. İkisi farklı
şey; panelin etiketi zaten dürüsttü ("FED, geniş").

`makro_cek.py`'ye Stooq'tan gerçek ICE DXY çeken bir fonksiyon eklendi. Başarısız
olursa sessizce FRED serisine düşüyor — panelde asla yanlış isim görünmüyor.

**DOĞRULANMADI:** bu ortamda dış ağ kapalıydı, fonksiyon çalıştırılamadı. İlk
çalışmada logda şunu ara:
- `DXY: Stooq'tan alindi` → çalışıyor
- `DXY: Stooq basarisiz` → alternatif plan: EVDS kurlarından ICE formülüyle
  kendimiz hesaplarız (EUR, JPY, GBP, CAD, SEK, CHF ağırlıklı geometrik ortalama)

### Dakika bütçesi

15 iş akışı → 9. pip cache, iş akışı birleştirme, `cancel-in-progress`,
timeout düşürme. Her iş akışına **hata bildirimi** eklendi — çöktüğünde
otomatik Issue açılıyor, sessiz bozulma bitiyor.

---

## Doğrulananlar ve doğrulanmayanlar

**Gerçek veriyle çalıştırılıp doğrulandı:**
- Kalem haritası — 472/472 şirket
- Tarama motoru — huni sayıları gerçek çıktı
- Dört sayfa da tarayıcıda açıldı; sekme, sıralama, arama, detay, huni kırılımı
  test edildi; yatay taşma yok, JS hatası yok
- Tüm iş akışı YAML'ları geçerli

**Doğrulanamadı (bu ortamda dış ağ kapalı):**
- Stooq DXY çekimi
- İş Yatırım / EVDS / FRED çağrıları
- Netlify proxy üzerinden veri akışı (yerelde 404, üretimde çalışması bekleniyor)
- İş akışlarının CI'da gerçekten çalışması

İlk push'tan sonra Actions sekmesini kontrol et.

---

## Sıradaki adımlar

1. **Fiyat geçmişi zaten 10 yıl** — `hisse_gecmis` dosyalarında 2016'dan bu yana
   2.533 gün var. Önceki notumda "2 yıl" demiştim, kod yorumuna bakarak; veri
   daha derinmiş. 20 yıla çıkarmak için İş Yatırım ucu testi hâlâ geçerli:

```bash
for y in 2000 2003 2006 2009; do
  n=$(curl -s -H "User-Agent: Mozilla/5.0" \
    "https://www.isyatirim.com.tr/_layouts/15/Isyatirim.Website/Common/Data.aspx/HisseTekil?hisse=GARAN&startdate=01-01-$y&enddate=31-12-$y" \
    | python3 -c "import sys,json;print(len(json.load(sys.stdin).get('value',[])))" 2>/dev/null || echo 0)
  echo "$y -> $n kayit"
done
```

2. **VBTS tedbir verisi** — taramanın en önemli eksik filtresi. KAP bildirimlerinden
   çekilebilir; risk katmanının kanıtı en sağlam parçası bu.

3. **Karantinadaki 3-5 şirketi KAP'tan doğrula** (AHGAZ 2025, ANELE 2023,
   DUNYH 2025). Rakam gerçekten öyle mi, yoksa çekimde mi bozuluyor?

4. **Anayasa** — tarama çalıştığına göre artık portföy kurallarını yazabiliriz.
