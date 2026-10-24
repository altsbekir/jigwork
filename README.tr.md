# jigwork

*Bir jig (kalıp) iş parçasını tutar ve aleti yönlendirir; böylece usta olmayan bir el bile
düzgün ve tekrarlanabilir kesimler yapar.* jigwork bunu küçük yerel dil modelleri için
yapar: 8 GB'lık bir dizüstü GPU'sunda çalışan bir modeli gerçek kodlama görevlerini güvenle
bitiren bir şeye dönüştürür.

> **Durum: pre-alpha.** Şimdilik yalnızca Linux.

## Fikir
Küçük modeller kısa ve net düzenlemelerde fena değil, uzun ve açık uçlu işlerde kötüdür.
Bu yüzden jigwork:

1. işi kabul maddeleri olan küçük görevlere böler (projendeki `docs/TASKS.md`),
2. her görevi ajana **yeni bir oturumda**, yalnızca o görev ve ilgili kurallarla verir,
3. ajanı kısıtlar: kabuk yok, proje dışına ya da kontrol dosyalarına yazma yok,
4. lint ve testleri kendisi, **ağı olmayan ve ev klasörünü görmeyen bir kutuda** çalıştırır,
5. hataları sınırlı sayıda düzeltme denemesi için geri verir,
6. geçeni commit eder, geçmeyeni yama olarak saklar, bir insan gerektiğinde durur.

## İlk sonuç
RTX 4060 Laptop (8 GB) + 32 GB RAM üzerinde Qwen3.6-35B-A3B (Q4_K_M), Qwen Code ile:
testleri olan 4 görevlik bir Python komut satırı uygulaması, 4/4 görev bitti, toplam yaklaşık
17 dakika. Ayrıntılar: `docs/bench-results.md`.

## Hızlı başlangıç
```fish
git clone https://github.com/altsbekir/jigwork.git ~/src/jigwork
uv tool install --editable ~/src/jigwork
jigw setup; and jigw doctor                   # ajan ayarları, sonra canlı güvenlik testi
jigw init --type python ~/Projeler/todo       # docs/ARCHITECTURE.md ve docs/TASKS.md'yi yaz
cd ~/Projeler/todo; and jigw run
```

## Komutlar
```
jigw init [--type python|c-cpp|generic]   proje oluştur ya da var olana ekle
jigw run [--one] | resume | status | check
jigw tasks lint                           çalıştırmadan önce docs/TASKS.md'yi denetle
jigw chat                                 aynı kısıtlamalarla etkileşimli ajan oturumu
jigw server start|stop|status|logs|setup|build
jigw setup | doctor                       ajan ayarları; donanım, sürümler, canlı güvenlik testi
jigw lang en|tr|auto, jigw completion fish
```

Geri kalan her şey, adım adım: [docs/tr/rehber.md](docs/tr/rehber.md).

English: [README.md](README.md)
