# jigwork kullanım rehberi

English: [docs/en/guide.md](../en/guide.md)

## jigwork ne yapar
Kendi bilgisayarında çalışan küçük bir model iyi kod yazabilir, ama yalnızca küçük ve açıkça
tarif edilmiş adımlarla. Ona büyük ve belirsiz bir iş verirsen yolunu kaybeder. jigwork böyle
bir modelin yine de gerçek bir proje üzerinde çalışabilmesini sağlar:

- İşi sen (ya da daha büyük bir model) **küçük görevlere** bölersin. Her görevin, ne zaman
  bitmiş sayılacağını söyleyen kısa bir koşul listesi olur.
- jigwork görevleri bir kodlama **ajanına** tek tek, her birini yeni bir oturumda verir.
  Ajan, modelin dosyaları okuyup düzenlemesini sağlayan programdır; jigwork Qwen Code kullanır.
- Ajan komut çalıştıramaz ve proje dışına yazamaz. Lint'i ve testleri jigwork kendisi,
  yalıtılmış bir **kutuda** (sandbox) çalıştırır.
- Bir kontrol başarısız olursa model hatayı görür ve düzeltmek için birkaç hak alır. Geçen iş
  git'e commit edilir; geçmeyen iş saklanır ve dosyalar eski haline döner.

Yani her adım denetlenir ve her adım geri alınabilir.

## İçindekiler
1. [Gerekenler](#1-gerekenler)
2. [Kurulum](#2-kurulum)
3. [İlk ayarlar](#3-ilk-ayarlar)
4. [Proje oluşturmak](#4-proje-oluşturmak)
5. [Görev yazmak](#5-görev-yazmak)
6. [Görevleri çalıştırmak](#6-görevleri-çalıştırmak)
7. [Ajanla doğrudan çalışmak](#7-ajanla-doğrudan-çalışmak)
8. [Model sunucusu](#8-model-sunucusu)
9. [Ayarlar](#9-ayarlar)
10. [Neler korunuyor, neler korunmuyor](#10-neler-korunuyor-neler-korunmuyor)
11. [Sorun giderme](#11-sorun-giderme)

## 1. Gerekenler
- **Linux.** macOS planlanıyor; Windows'ta WSL2 kullan.
- **Python 3.11 ya da üstü**, **git** ve **bubblewrap** (jigwork'ün kutu için kullandığı `bwrap`
  komutu). Arch'ta: `sudo pacman -S bubblewrap`.
- **Qwen Code** (ajan): `npm install -g @qwen-code/qwen-code`. jigwork 0.26.0 sürümüyle test
  edildi; `jigw doctor` sendeki sürümü denetler.
- **Bir model sunucusu**: modeli çalıştıran ve isteklere OpenAI uyumlu bir API ile cevap veren
  program. jigwork, 8 GB GPU'da Qwen3.6-35B-A3B çalıştıran llama.cpp için hazır ayarlarla gelir
  ve onu senin için derleyip çalıştırabilir (bölüm 8). Bu türden başka sunucular da olur:
  Ollama, LM Studio ya da başka bir makinedeki bir sunucu.

## 2. Kurulum
jigwork kaynağından, [uv](https://docs.astral.sh/uv/) ile kurulur:

```fish
git clone https://github.com/altsbekir/jigwork.git ~/src/jigwork
uv tool install --editable ~/src/jigwork
jigw --version
```

`--editable` sayesinde kurulan `jigw` komutu o klasördeki kodu çalıştırır; güncellemek için
orada `git pull` yapman yeterli. Kabuğun `jigw`'yi bulamazsa uv'nin komut klasörünü PATH'e ekle
(fish: `fish_add_path ~/.local/bin`) ve yeni bir terminal aç.

Komutun adı `jigw`; `jigwork` aynı komutun uzun adıdır.

**İsteğe bağlı:** fish için sekme tamamlama. Komutlardan üretildiği için bir güncellemeden sonra
bunu yeniden çalıştır:

```fish
jigw completion fish > ~/.config/fish/completions/jigw.fish
```

**Dil:** jigwork İngilizce ve Türkçe konuşur. Sistem dilini izler; kendin seçmek için
`jigw lang tr` ya da `jigw lang en`, yeniden sistem dilini izlemesi için `jigw lang auto`.

## 3. İlk ayarlar
Bunları bir kez çalıştır:

```fish
jigw setup
jigw doctor
```

**`jigw setup`**, ajanı kısıtlayan ayarları Qwen Code'un ayar dosyasına,
`~/.qwen/settings.json`'a yazar: komut çalıştıran araçlar kaldırılır, yazma proje içiyle
sınırlanır, jigwork'ün dayandığı dosyalar korunur ve Qwen Code doğru context boyutu ve örnekleme
ayarlarıyla model sunucuna yönlendirilir. Mevcut ayarların korunur; eski dosya önce yedeklenir
(`settings.json.backup-<tarih>`).

**`jigw doctor`** makineni denetler: donanım, kurulu araçlar, model sunucusu ve ajan ayarları.
Sonra korumaları gerçekten dener: Qwen Code'u senin ayarlarınla, bilinen her kaçış yolunu deneyen
sahte bir modele karşı çalıştırır ve kutuyu gerçek ev klasörüne karşı sınar. Sisteminde hiçbir
şeyi değiştirmez. Her satırda ✔ görmelisin; görmediğin satırlarda ne yapman gerektiğini söyler.

Model sunucusunu da jigwork'ün çalıştırmasını istiyorsan bölüm 8'e bak (`jigw server setup`).

## 4. Proje oluşturmak
```fish
jigw init --type python ~/Projeler/todo
```

Tipler: `python`, `c-cpp`, `generic` (varsayılan; sen eklemedikçe kontrol yoktur).

- Klasör **boşsa ya da yoksa**, jigwork projeyi oluşturur, onu bir git deposu yapar ve ilk hali
  commit eder.
- Klasörde **zaten dosyalar varsa**, jigwork yalnızca eksik olanları ekler. Hiçbir dosyanın
  üzerine yazmaz ve commit atmaz; değişikliklere `git status` ile bakıp kendin commit et. Zaten
  bir `AGENTS.md`'n varsa jigwork ona dokunmaz, eklemek isteyebileceğin satırları gösterir.

Ortaya çıkanlar:

| Yol | Ne işe yarar |
|---|---|
| `AGENTS.md` | Ajanın her oturumda okuduğu kurallar. Kısa tut. |
| `docs/ARCHITECTURE.md` | Programın ne yaptığı, klasör düzeni ve ana kararlar. **Önce bunu doldur**: ajan dosya oluşturmadan önce bunu okur. |
| `docs/TASKS.md` | Görev listesi (bölüm 5). |
| `docs/STATUS.md` | Biten her görev için bir satırlık kayıt. jigwork yazar. |
| `.jigwork/config.toml` | Bu projenin nasıl denetleneceği: lint, testler, sınırlar (bölüm 9). |
| `.jigwork/work/` | Loglar, kaydedilen yamalar. Commit edilmez. |
| `.qwen/` | Qwen Code'un bu projedeki dosyaları; örneğin ona verilen kodlama kuralları ("skill"ler). |

Mimariyi ve görev listesini yazmak planlama işidir; bunu daha büyük bir model (ya da sen) iyi
yapar. Yerel modelin işi görevleri yerine getirmektir.

## 5. Görev yazmak
`docs/TASKS.md` içindeki bir görev şöyle görünür:

```markdown
## T1: Parse a todo line
status: pending
type: code
files: src/todo/model.py, tests/test_model.py
task: Write parse_line(text) that turns "[x] buy milk" into Todo(done=True, title="buy milk").
acceptance:
- "[ ] a" gives done=False, title="a"
- "[x] a" gives done=True
- any other format raises ValueError
- tests for all three cases exist and pass
```

| Alan | Ne yazılır |
|---|---|
| `## T1: ...` | Bir numara ve kısa bir başlık. Görevler bu sırayla çalışır. |
| `status` | `pending` yaz. jigwork bunu `done` ya da `failed` yapar; sen `skip` yapabilirsin. |
| `type` | `code`, `test` ya da `docs`. Prompt'a hangi kodlama kurallarının gireceğini belirler. |
| `files` | Ajanın okuması ya da değiştirmesi gereken dosyalar. Henüz olmayan dosyalar da yazılabilir; ajana onları oluşturması söylenir. |
| `task` | Ne yapılacağı, birkaç cümleyle. |
| `acceptance` | Görevin ne zaman bitmiş sayılacağı: denetlenebilir, somut maddeler. |

Alan adları ve görev metni İngilizce yazılır: metin olduğu gibi modele gider, model de
İngilizceyi en iyi anlar.

**Görevleri küçük tut:** her biri tek bir iş olsun, ideali bir ile üç dosya, tek başına test
edilebilsin. Tekrar tekrar başarısız olan bir görev neredeyse her zaman fazla büyük ya da fazla
belirsizdir; onu böl ya da kabul maddelerini netleştir.

Çalıştırmadan önce dosyayı denetle:

```fish
jigw tasks lint
```

Eksik bir kabul listesi, bilinmeyen bir durum ya da iki kez kullanılmış bir numara gibi
hataları gösterir.

## 6. Görevleri çalıştırmak
```fish
jigw run           # bekleyen bütün görevleri sırayla yap
jigw run --one     # yalnızca sıradakini
jigw status        # görev listesini göster
jigw check         # ajan olmadan, kontrolleri şu anki koda karşı çalıştır
```

Commit edilmemiş değişikliklerin varken jigwork başlamaz. Böylece her görev temiz bir commit'ten
başlar ve git ile geri alınabilir.

**Her görev için olanlar:**
1. Yeni bir ajan oturumu yalnızca bu görevi alır: metnini, dosyalarını, kabul maddelerini,
   çalışma kurallarını ve görev tipine uygun kodlama kurallarını. İlerleme ekranda görünür.
2. Oturum bitince jigwork, ajanın git'in kendi ayarlarına dokunmadığını denetler ve ajanın
   değiştirdiği korunan dosyaları geri alır.
3. Basit biçim sorunları otomatik düzeltilir (Python'da `ruff format`), sonra kontroller kutuda
   çalışır. İlk başarısız kontrol gerisini durdurur.
4. **Bir kontrol başarısız olursa** çıktısı bir düzeltme denemesi olarak ajana geri verilir.
   Varsayılan olarak bir görevin toplam üç deneme hakkı vardır.
5. **Kontroller geçerse** görev `done` olur, `docs/STATUS.md`'ye bir satır eklenir ve her şey
   commit edilir.
6. **Bütün denemeler başarısız olursa** ajanın son hali `.jigwork/work/` altına yama olarak
   kaydedilir, dosyalar eski haline döner, görev `failed` olur ve çalışma durur. Sonraki görevler
   bekler, çünkü genellikle bu göreve dayanırlar. Görevi küçültüp ya da netleştirip yeniden
   `status: pending` yap, ya da onsuz devam etmek için `status: skip` yap.

**Ajan bir komuta ihtiyaç duyduğunda.** Ajan paket kuramaz, migration çalıştıramaz. Bir görev
bunu gerektirirse çalışma durur ve komutu gösterir. O komut **senin yetkilerinle ve kutunun
dışında** çalışır; çalıştırmadan önce oku. Komutu kendin çalıştır, sonra devam et:

```fish
jigw resume
```

Eksik bir Python paketi için daha iyi yol, onu `pyproject.toml`'daki `dependencies` listesine
eklemektir: jigwork onu test ortamına kendisi kurar.

## 7. Ajanla doğrudan çalışmak
```fish
jigw chat
```

Qwen Code'u bulunduğun projede, `jigw run` ile aynı kısıtlamalarla, olağan bir sohbet için
açar. Ev klasöründe, bir git deposunun dışında ya da Qwen Code'un "her şeyi onayla" modunda
(`--yolo`) açılmayı reddeder; commit edilmemiş değişiklik varsa önce sorar. Çıktığında git
ayarlarını denetler ve bir değişiklik olduysa geri almayı önerir. Verdiğin argümanlar Qwen
Code'a geçer; örneğin `jigw chat -c` son oturumu sürdürür.

## 8. Model sunucusu
jigwork'ün çalışan bir model sunucusuna ihtiyacı var, ama onu kimin başlattığı önemli değil:
sen, bir masaüstü kısayolu, başka bir araç ya da jigwork'ün kendisi. jigwork şu kurallara uyar:

- **Zaten çalışan bir sunucu** kullanılır ve jigwork tarafından asla kapatılmaz.
- **Çalışan bir sunucu yoksa** ve jigwork bir sunucu yönetiyorsa (aşağıya bak), `jigw run` ve
  `jigw chat` onu başlatır, modelin yüklenmesini bekler ve bitince yeniden kapatır. Açık kalmasını
  istiyorsan `stop_when_done = false` ayarla (bölüm 9).
- **Sunucu bir görevin ortasında kapanırsa** (sen kapatırsın, çöker), o deneme görevin
  hakkından düşmez. Ajanın o ana kadar yazdıkları yamaya kaydedilip geri alınır ve jigwork beş
  dakikaya kadar bekler. Birinin kapattığı sunucuyu asla kendisi açmaz. Sunucu geri gelirse
  deneme baştan yapılır; gelmezse çalışma durur, sonra `jigw resume` ile devam edersin.
- **Sunucu, ajanın beklediğinden farklı ayarlarla çalışıyorsa** (örneğin daha küçük bir
  context ile), jigwork bunu çalışma başlamadan söyler.

**llama.cpp'yi jigwork'e yönettirmek.** jigwork llama.cpp'yi derleyip kullanıcı hesabının bir
arka plan servisi (systemd kullanıcı servisi) olarak çalıştırabilir:

```fish
git clone https://github.com/ggml-org/llama.cpp ~/llama.cpp   # bir kez
jigw server build     # ~/llama.cpp'yi güncelle (git pull) ve CUDA ile derle
jigw server setup     # servisi, modeline ve GPU'na uygun ayarlarla oluştur
jigw server start | stop | status | logs   # başlat, durdur, durumunu gör, logunu izle
```

`jigw server build` için CUDA araç takımı gerekir (`nvcc`; Arch'ta: `sudo pacman -S cuda`).

Hazır ayarlar (bir "profil") 8 GB GPU ve 32 GB RAM üzerinde Qwen3.6-35B-A3B içindir: 64K
context, GPU'nun otomatik doldurulması, modelin önerdiği örnekleme. Bu ayarlar sunucunun prompt
önbelleğini oturumlar arasında sıcak da tutar; hız buradan gelir: sunucu başladıktan sonraki
ilk istek yaklaşık bir buçuk dakika sürer, sonraki oturumlar yaklaşık on saniyede başlar.

**Başka bir sunucu kullanmak** (Ollama, LM Studio, uzak bir makine): adresini
`~/.qwen/settings.json` içinde yaz (model sağlayıcının `baseUrl` değeri) ve jigwork'e hiçbir
şeyi yönetmemesini söyle: ayarlarında `manage = "never"` (bölüm 9).

## 9. Ayarlar
**Tek bir proje için:** `.jigwork/config.toml`. `jigw init` yazar; çoğunlukla yalnızca
kontrolleri değiştirirsin.

```toml
[prepare]
kind = "python-venv"   # proje dışında pytest, ruff ve pyproject.toml'daki bağımlılıklarla
                       # bir test ortamı; başka projeler için "none"
[autofix]
command = "ruff format --no-cache --quiet . ; ruff check --no-cache --fix --quiet . ; true"
[checks]               # bu sırayla çalışır; ilk başarısızlık gerisini durdurur
lint = "ruff check --no-cache ."
test = "python -m pytest -q -p no:cacheprovider"
[skills]               # görev tipine göre ajana verilen kodlama kuralları
code = ["python-code", "python-test"]
[limits]
attempts = 3           # ilk deneme ve düzeltmeler
agent_wall_time = "45m"
agent_tool_calls = 80
check_timeout = 600    # kontrol başına saniye
```

Kontrolü olmayan bir proje de çalışır, ama o zaman bir görev ajanın sözüne güvenilerek kabul
edilir; jigwork bu konuda uyarır.

**Kullanıcı hesabın için:** `~/.config/jigwork/config.toml`. Buradaki her şey isteğe bağlıdır.

```toml
lang = "tr"                      # `jigw lang` bunu yazar
[server]
profile = "qwen3.6-35b-a3b/rtx4060-laptop-8gb"
llama_dir = "~/llama.cpp"
model_file = "~/models/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
port = 8091
manage = "auto"                  # "never": jigwork hiçbir sunucuyu başlatmaz ya da kapatmaz
stop_when_done = true            # jigwork'ün başlattığı sunucu çalışma bitince kapatılır
outage_wait = 300                # giden bir sunucu için kaç saniye beklenir
load_wait = 600                  # modelin yüklenmesi için kaç saniye beklenir
```

Portu, profili ya da model dosyasını değiştirdikten sonra önce `jigw server setup`, sonra
`jigw setup` çalıştır; böylece sunucu ile ajan aynı ayarlarda buluşur.

## 10. Neler korunuyor, neler korunmuyor
**Korunanlar.** `jigw doctor` bunların her birini senin makinende dener:
- **Ajan komut çalıştıramaz.** Komut çalıştırabilecek her araç kaldırılır; yalnızca
  talimatlarda yasaklanmaz. Küçük bir modele "kabuğun yok" dersen başka bir yol aramaya koyulur.
- **Ajan yalnızca proje içine yazabilir**; git'in klasörüne (`.git/`), kendi ayarlarına
  (`.qwen/`), jigwork'ün dosyalarına (`.jigwork/`, `AGENTS.md`, `docs/TASKS.md`,
  `docs/STATUS.md`), `pyproject.toml`'a ve `.env` dosyalarına yazamaz. Bir projenin kendi Qwen
  Code ayarları bunu kapatamaz.
- **git gözetlenir.** `.git/config` içindeki tek bir satır, git'i bir sonraki kullanışında
  bilgisayarında bir komut çalıştırmaya zorlayabilir. jigwork bu dosyaları her oturumdan sonra
  denetler.
- **Kontroller bir kutuda çalışır**: ağ yoktur; ev klasörün, `/tmp` ve `/run` görünmez; git'in
  klasörü, korunan dosyalar ve test ortamı orada salt okunurdur.
- **Ajanın web erişimi yoktur.**

**Bilerek korunmayanlar:**
- **Ajanın senden çalıştırmanı istediği komutlar** araya hiçbir şey girmeden senin olarak
  çalışır. Onları oku; yanlış yazılmış paket adlarına dikkat et.
- **Projenin kodunu kendin çalıştırmak**, modelin yazdığı kodu hiçbir kutu olmadan çalıştırmak
  demektir.
- `pyproject.toml`'daki **bağımlılıklar** bilgisayarına pip ile kurulur. Ajan bu dosyayı
  değiştiremez; içine neyin gireceğine sen karar verirsin.
- Qwen Code'a eklediğin **MCP sunucuları** jigwork tarafından sınırlanmaz. Varsa `jigw doctor`
  uyarır.
- **`qwen`'i doğrudan çalıştırmak**, yani `jigw` olmadan, `jigw setup`'ın yazdığı ayarları
  korur, ama jigwork'ün git ve korunan dosyalar üzerindeki denetimlerini değil.

## 11. Sorun giderme
| Ne görüyorsun | Ne yapmalı |
|---|---|
| "Güvenlik ayarları eksik" | `jigw setup` çalıştır. |
| "Yanıt veren bir model sunucusu yok" | Sunucunu başlat ya da jigwork'e bir tane yönettir: `jigw server setup`. |
| Bir çalışmanın ilk isteği yavaş | Normal: prompt önbelleği ısınırken yaklaşık 1,5 dakika. Saatlerce boşta kalmış bir sunucu ilk başta daha yavaş olabilir. |
| Bir görev sürekli başarısız oluyor | `.jigwork/work/log/` içindeki kontrol çıktısını ve son denemenin yamasını oku. Genellikle görev fazla büyüktür ya da kabul maddeleri belirsizdir. |
| "Yarıda kalan denemenin değişiklikleri yamaya kaydedildi" | Model sunucusu bir görevin ortasında gitti; bölüm 8'e bak. |
| Kutu ya da ajanla ilgili her şey | `jigw doctor` çalıştır; yardım isterken çıktısını da ekle. |

`jigw run` ve `jigw resume` **çıkış kodları** (betikler için): `0` bitti (ya da yapılacak bir
şey yok), `1` bir görev başarısız oldu ya da çalışma başlayamadı (mesaj nedenini söyler), `2` ajan
senden bir komut çalıştırmanı istiyor, `3` model sunucusu gitti, `130` Ctrl-C ile durduruldu.
