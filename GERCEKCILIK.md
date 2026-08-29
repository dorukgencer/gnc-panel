# Gerçekçilik Paketi — üç açığın kapatılması

Geçen turda testin üç yerde gerçek dışı olduğunu tespit etmiştik. Üçünün de
çözümünü buldum ve sisteme ekledim. **Ama ikisi henüz doğrulanmadı** — bu
ortamda dış ağ kapalı, uçları canlı test edemedim. Aşağıdaki sıra bu yüzden
önemli.

---

## Açık 1 — Hayatta kalma yanlılığı (borsadan çıkan şirketler)

**Sorun:** Evren bugün borsada olan şirketlerdi. 2021-2025 arasında kotasyondan
çıkan, birleşen, konkordatoya giden şirketler veride hiç yoktu. Test döneminde
21+ gün işlem görmeyen tek bir hisse bulamamıştım — çünkü öyle şirketler
dosyalarda hiç yoktu. Sistem hiç batan şirket seçmedi, çünkü seçebileceği
batan şirket yoktu.

**Çözüm:** KAP'ın şirket listesi ucu aktif ve pasif şirketleri ayrı veriyor:

```
GET https://kap.org.tr/tr/api/company/items/IGS/P     → kotasyondan çıkmışlar
GET https://kap.org.tr/tr/api/company/items/IGS/A     → aktifler
```

Aktif listede bile `payIslemDurumu` alanı var: `"0"` ise payı işlem görmüyor.
Bu uç araştırmada **gerçek veri döndürerek doğrulandı** (ABANA, ADANA, AKIPD
gibi çıkmış kodlar geliyor).

**Yeni dosya:** `kap_evren_cek.py`

- Normal çalışma: günlük anlık görüntü alır, bir öncekiyle farkını çıkarır,
  aktiflikten düşen kodları **çıkış olayı** olarak kaydeder. Bugünden sonraki
  çıkışların tarihini böylece kendimiz üretiriz.
- `--doldur`: çıkmış şirketlerin **fiyat geçmişini** çeker ve
  `hisse_gecmis_cikan/` klasörüne yazar. Geçmiş test bu klasörü de okur;
  şirket evrene geri girer ve **serisinin bittiği gün fiili çıkış tarihi olur.**
  Asıl çözüm budur.

**Dürüst sınır:** KAP bu uçta çıkarılma tarihini vermiyor. Geçmiş çıkış
tarihlerini fiyat serisinin bitişinden türetiyoruz — bu iyi bir yaklaşım ama
resmî tarih değil.

---

## Açık 2 — VBTS tedbiri

**Sorun:** Taramanın "kanıtı en sağlam katmanı" risk temizliğiydi ama en önemli
filtresi çalışmıyordu. Testte de tek fiyat işlem yöntemine alınmış bir hisse
serbestçe alınıp satılabiliyor sayılıyordu.

**Çözüm — beklediğimden iyi:** VBTS kararları KAP'ta yayınlanıyor ve arşiv
**geriye dönük sorgulanabiliyor.** Her bildirim tedbirin başlangıç ve bitiş
tarihini metninde taşıyor. Yani 2021'e kadar geri gidebiliyoruz; "bugünden
itibaren biriktir" demek zorunda değiliz.

```
POST https://www.kap.org.tr/tr/api/disclosure/members/byCriteria
     {"fromDate":"...","toDate":"...","mkkMemberOidList":[],"subjectList":[]}
GET  https://www.kap.org.tr/tr/api/notification/attachment-detail/{index}
```

**Yeni dosya:** `kap_tedbir_cek.py` — aylık pencerelerle tarar (yanıt 2000 kayıt
sınırlı), VBTS bildirimlerini süzer, metinden hisse kodu + tedbir türü +
tarih aralığı çıkarır, `tedbir.json` üretir.

Yedi tedbir türü tanınıyor: brüt takas, kredili işlem yasağı, açığa satış
yasağı, piyasa emri yasağı, tek fiyat işlem yöntemi, emir paketi, yatırımcı
bazlı kısıtlama.

**Nerede kullanılıyor:**
- **Tarama:** yeni bir kapı eklendi — aktif tedbirliler ve son 12 ayda iki kez
  tedbir görenler eleniyor. Veri geldiğinde "çalışmayan filtreler" listesinden
  de otomatik çıkıyor.
- **Geçmiş test:** karar gününde tedbirli olan hisse evrene girmiyor.

**Önemli karar — vekil kullanmıyoruz:** BIST'in VBTS tetikleme eşikleri kamuya
açık değil; beş bağımsız kaynakta doğrulandı, yönerge kasten "güçlü emareler"
gibi belirsiz ifade kullanıyor. Bu yüzden tedbiri fiyat/hacimden **tahmin
etmeye çalışmıyoruz.** Kalibre edilemeyen bir tahmin, veri yokluğundan daha
tehlikelidir — yanlış bir kesinlik hissi verir.

---

## Açık 3 — Bir günlük bilgi avantajı (ÇÖZÜLDÜ, ölçüldü)

**Sorun:** Karar günü kapanışıyla karar verilip **aynı kapanıştan** işlem
yapılıyordu. Gerçekte kapanışı görüp ertesi gün alırsın.

**Çözüm:** Seçim karar günü yapılıyor, işlem **ertesi işlem gününün
kapanışından** gerçekleşiyor. Bu tek başına çalıştırıldı ve etkisi ölçüldü:

| Strateji | Aynı gün | T+1 | Fark |
|---|---:|---:|---:|
| Trend | %101.4 | %99.6 | −1.8p |
| Sistem | %76.0 | %74.8 | −1.2p |
| Büyüme | %70.4 | %65.4 | −5.0p |
| Ters | %25.7 | %22.4 | −3.3p |

Yani bir günlük avantaj 1–5 puan değerindeymiş. Ana sorun değil, ama artık yok.

---

## Yapman gereken sıra

**Adım 1 — Tanı (önce bunlar, 2 dakika).** Uçlar gerçekten çalışıyor mu?
Actions sekmesinden **KAP evren + VBTS tedbir** iş akışını elle çalıştır, ya da
yerelde:

```bash
python kap_evren_cek.py --tani
python kap_tedbir_cek.py --tani
```

Ne göreceksin:
- `kap_evren_cek.py --tani`: aktif/pasif sayıları ve **pasif kodların fiyat
  geçmişinin çekilip çekilemediği**. Satır sayısı >0 gelenler evrene
  konabilir demektir — bu, hayatta kalma yanlılığının tam çözümü.
- `kap_tedbir_cek.py --tani`: tek pencere çalışır ve **ham JSON şemasını
  ekrana basar.** Şema beklediğimden farklıysa orada görürsün; bana yapıştır,
  ayrıştırıcıyı düzeltirim.

**Adım 2 — Tek seferlik dolum (uzun sürer).** Tanı temizse, Actions'ta
**Run workflow** ile iki girdiyi de `evet` yap:
- `tam_tedbir_dolumu: evet` → VBTS arşivini 2021'den bugüne çeker
- `cikan_fiyat_dolumu: evet` → çıkmış şirketlerin fiyat geçmişini çeker

Bu iş saatler sürebilir; timeout 180 dakikaya ayarlı. Kotan sıfırlandıktan
sonra çalıştır.

**Adım 3 — Testi yeniden çalıştır.** Dolum bitince `gecmis_test.py` otomatik
çalışıyor. Sonuçların önceki turdan **belirgin biçimde düşmesini bekliyorum** —
çünkü artık batan şirketler evrende ve tedbirli hisseler alınamıyor. Düşmezse
bir şey yanlış demektir, o zaman tekrar bakarız.

---

## Hâlâ çözülmemiş olanlar

Dürüst olmak için: bunlar duruyor.

- **Tavan/taban günleri.** Tavana kilitli hisseyi o fiyattan alamazsın; test
  hâlâ alabiliyor. Çözümü için gün içi yüksek/düşük verisi lazım, elimizde
  sadece kapanış var.
- **Temettü.** Serinin temettüye göre düzeltilip düzeltilmediğini
  belirleyemedim — temettü tarihleri elimizde yok. Düzeltilmemişse tüm
  stratejiler eşit oranda eksik ölçülüyor (yönü lehimize).
- **Bedelli sermaye artırımı.** Piyasa değeri formülüm bedelsizde matematiksel
  olarak tam doğru (doğrulandı), bedellide yaklaşık. Ardışık çeyreklerde 35
  vaka bedelli şüphesi taşıyor.
- **Geçmiş endeks üyeliği.** "O tarihte BIST 100'de miydi" bilgisi yok.
- **Sermaye artırımı etkisi.** En büyük açık bulgu buydu: sermaye hareketi olan
  şirketleri çıkarınca Sistem %76'dan %57'ye düşüyordu. Bu bir veri hatası
  değil, gerçek bir rejim etkisi — ama Sistem'in kuralları bunu açıklamıyor.
  Bu, veriyle değil **kural tasarımıyla** çözülecek bir konu.
