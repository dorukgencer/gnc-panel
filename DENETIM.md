# Denetim ve Yeni Sistem — 29 Ağustos 2026

Üç saatlik denetim ve inşa turunun kaydı. Önce bulunan hatalar, sonra eklenenler.

---

## Bulunan ve düzeltilen hatalar

### 1. Sektör rotasyonu — kök nedeni bulunmamış anomali çözüldü

`rotasyon_hesapla.py` içinde şu not duruyordu:

> *"Teknoloji sektorunun %37 gibi mantik disi bir agirlikla ciktigi tespit edildi,
> kok neden HENUZ KESIN degil"*

**Kök neden:** BIST endeksleri her zaman birbirinden ayrık değil. Veride tam olarak
bir kapsama ilişkisi var:

```
XUTEK (Teknoloji, 42 hisse)  ⊃  XBLSM (Bilişim, 38 hisse)
```

Bilişim, Teknoloji'nin **alt endeksi**. Eski kod ikisini ayrı sektör sanıyor ve
hisse→sektör sözlüğünü kurarken "son gelen kazanır" davranıyordu: 38 hisse XBLSM'e
yazılıyor, XUTEK'te **yalnızca 4 hisse** kalıyordu. İçlerinde ASELS gibi çok büyük
bir şirket olduğu için XUTEK'in ağırlığı 4 hisseden hesaplanıp şişiyordu. Ayrıca
aynı hisseler rotasyon grafiğinde **iki kez** temsil ediliyordu.

**Çözüm:** `sektor_haritasi.py` — kapsama ilişkilerini veriden **otomatik** bulur,
alt endeksi sektör evreninden çıkarır, hisseleri üst endekse atar. Elle liste
tutulmaz; yeni bir alt endeks eklenirse kendiliğinden yakalanır.

| | Önce | Sonra |
|---|---|---|
| Sektör sayısı | 22 (biri çift) | 21 |
| Hisse kapsamı | 474 / 520 (%91) | **482 / 482 (%100)** |
| XUTEK | 4 hisse | 42 hisse |
| Ağırlık toplamı | çifte sayımlı | tam %100 |

### 2. Değerleme aynı hatadan etkilenmiş

`deger_hesapla.py` de aynı bozuk eşlemeyi kullanıyordu:

| | Önce | Sonra |
|---|---|---|
| XUTEK F/K | 65.59 (2 şirket, düşük güven) | **18.99 (23 şirket, güvenli)** |
| XBLSM | ayrı sektör olarak vardı | kaldırıldı |
| Düşük güvenli sektör | daha fazla | 2 (XILTM, XSPOR — gerçekten küçükler) |

### 3. Büyüme dönemleri yanlış sıralanıyordu

`buyume_hesapla.py` dönemleri **metin olarak** sıralıyordu: `"2024/12"` < `"2024/3"`
çünkü `"1" < "3"`. Sonuç:

```
ÖNCE:   2024/12, 2024/3, 2024/6, 2024/9, 2025/12, 2025/3, ...
SONRA:  2024/3, 2024/6, 2024/9, 2024/12, 2025/3, 2025/6, ...
```

### 4. Ana sayfa JavaScript hatasıyla kırılıyordu

`gnc_panel.html` ve `sektor-rotasyonu.html` iki fonksiyon çağırıyordu ama
**hiçbir yerde tanımlı değillerdi**: `gncVeriZamani` ve `gncEnEskiTarih`.
`sektor-rotasyonu.html` içindeki yorum *"Fonksiyon artık ortak.js'te"* diyor —
taşıma yarım kalmış. Sonuç: Genel Bakış sayfası `gncVeriZamani is not defined`
ile kırılıyor, veri zamanı etiketlerinin hiçbiri yazılmıyordu.

İkisi de `ortak.js`'e yazıldı. `gncEnEskiTarih` bilerek **en eski** zaman damgasını
döndürür — bir kutu birkaç dosyadan besleniyorsa, en tazeyi göstermek "her şey
güncel" izlenimi verir; kutu en eski kaynağı kadar tazedir.

### 5. Yerelde bütün sayfalar boş görünüyordu

`gncVeriCek` sadece Netlify proxy'sini deniyordu. Yerelde açıldığında bütün
sayfalar "veri henüz yok" diyordu ve bu, **gerçek bir veri hatasından ayırt
edilemiyordu.** Yerel yedek eklendi; üretimde o satıra hiç gelinmez.

Etki (yerel testte sayfa metni): rotasyon 664 → **7.831** karakter,
şirketler 1.010 → **33.390** karakter.

### 6. Haftalık hizalama kırılganlığı (gizli, henüz zarar vermemiş)

Rotasyonun göreli güç hesabı iki seriyi **indeks** ile eşleştiriyordu — i'inci
eleman iki seride de aynı hafta varsayılıyordu. Şu anki veride haftalar birebir
örtüşüyor, yani **sonuç doğruydu**; ama bir sektör serisinde tek bir hafta eksik
olsa hesap sessizce kayar ve yanlış haftaları karşılaştırmaya başlardı.
Artık eşleştirme hafta anahtarı üzerinden yapılıyor.

---

## Yeni: Kural Laboratuvarı

"4 kuralla test edeyim, sonra 3'e düşüreyim, sonra 6 yapayım" isteğinin karşılığı.

**12 süzgeç · 8 sıralama · 5 nakde geçme koşulu.** Soldan seçersin, sonuç anında
gelir — çünkü 920 kombinasyon önceden hesaplanmıştır.

### Neden hızlı

Saf yaklaşım her kombinasyon için testi baştan çalıştırmaktır: 60 karar günü ×
450 şirket ≈ 15 saniye. 900 kombinasyon = 3,5 saat. Kullanılamaz.

Bunun yerine ölçümler **bir kez** hesaplanıp bir panele (tarih × şirket × ölçü)
yazılıyor. Sonrası saf süzme ve sıralama. **920 kombinasyon 4,5 dakikada.**

### Etkisiz kural tespiti

Bir kural eklendiğinde sonuç hiç değişmiyorsa o kural, o bağlamda etkisizdir ve
arayüzde işaretlenir. İlk taramada yakalanan örnek:

> **Borçluluk süzgeci, "ucuz" sıralamasıyla birlikte 24 kombinasyonun hepsinde
> etkisiz.** Sebebi mantıklı: FD/FAVÖK net borcu zaten paya dahil eder, borçlu
> şirket otomatik olarak "pahalı" görünür. Yani borçluluk kuralı zaten
> değerlemenin içinde.

Etkisiz kuralı sistemde tutmak, **olmayan bir korumaya güvenmektir.**

### Rejim ayrıştırması

Faiz ve enflasyondan dört rejim türetiliyor:

- reel faiz = politika faizi − yıllık TÜFE
- faiz yönü = son 6 aydaki değişim

Doğrulandı ve tarihsel gerçekle örtüşüyor: 2022-06'da faiz %14 / TÜFE %78.6 →
reel −%64.6; 2025-06'da faiz %46.9 / TÜFE %35 → reel +%11.8.

Bir kural setinin ortalaması, hangi ortamda çalıştığını gizler. Sayfada her
kombinasyonun rejim bazında getirisi ve BIST 100 farkı var.

### Nakde geçme

Beş seçenek: yok · XU100 200g altındaysa · XU100 300g altındaysa · yeterli aday
yoksa · portföy %15 düştü ve ortam bozuksa. Açıp kapatarak karşılaştırılabilir.

### Aşırı uydurmaya karşı

Yüzlerce kombinasyon deneyip en iyisini seçmek, veriye uydurmanın kendisidir.
Buna karşı üç koruma kodun içinde:

1. Her kombinasyon **yıl yıl** raporlanır; en kötü yılı eksi olan işaretlenir.
2. Her kombinasyon **rejim bazında** raporlanır; bir rejimde negatifse işaretlenir.
3. **Kontrol grubu** (hiç kural yok) her zaman listede; onu geçemeyen kombinasyon,
   kural eklemenin zarar verdiği anlamına gelir.

Sıralama puanı getiriden değil, **getiri/düşüş oranından** hesaplanır ve her uyarı
puanı düşürür. Liste bir **keşif aracıdır, seçim gerekçesi değildir.**

---

## Sistemin son hâli

**Altı sayfa**, hepsi tarayıcıda test edildi — JS hatası yok, yatay taşma yok,
ölü link yok:

| Sayfa | İş |
|---|---|
| Genel Bakış | Ortam okuması |
| Sektör Rotasyonu | Ortamın sektör boyutu |
| Tarama | Eleme motoru — 472 şirket → aday listesi |
| Şirketler | Tek şirket derinlemesine |
| Portföy Testi | 8 strateji, 5 yıl |
| **Kural Laboratuvarı** | 920 kombinasyon, rejim, nakde geçme |

**On bir iş akışı.** Yeni: `kural-lab.yml` (Pazar akşamı, elle tetiklenirse farklı
kural sayılarıyla da çalışır).

---

## Hâlâ açık olanlar

Dürüstlük için — bunlar duruyor ve veriyle değil, ya dolum ya kural tasarımıyla
çözülecek:

- **Hayatta kalma yanlılığı.** `kap_evren_cek.py --doldur` çalıştırılana kadar
  borsadan çıkanlar evrende yok.
- **VBTS tedbiri.** `kap_tedbir_cek.py` çalıştırılana kadar tedbirli hisseler
  serbestçe alınabiliyor sayılıyor. İkisi de sayfada açıkça "çalışmayan filtre"
  olarak gösteriliyor.
- **Sermaye artırımı etkisi.** Sermaye hareketi olan şirketleri çıkarınca sistemin
  üstünlüğü %76'dan %57'ye düşüyordu. Veri hatası değil, gerçek bir rejim etkisi —
  ama kurallar bunu açıklamıyor. Kural tasarımıyla çözülecek.
- **Tavan/taban günleri** ve **temettü düzeltmesi** — gün içi veri ve temettü
  tarihleri olmadan çözülemez.
