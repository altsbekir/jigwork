# Qwen Proje Kalıbı

## Kurulum (bir kez)
```fish
fish kur.fish
exec fish
```
Kalıp `~/.local/share/qwen-kalip` altına, komutlar `~/.config/fish/functions` altına kurulur.
Kalıbı güncellemek için klasörü düzenleyip `fish kur.fish` komutunu tekrar çalıştır.

## Komutlar
| Komut | Ne yapar |
|---|---|
| `orkestra` | `docs/TASKS.md`'deki bekleyen görevleri sırayla Qwen'e yaptırır, kontrol eder, commit atar |
| `orkestra tek` | Yalnızca sıradaki görevi yapar |
| `orkestra durum` | Görev listesini gösterir |
| `orkestra kontrol` | Lint/test'i şu anki koda karşı çalıştırır (kutuda) |
| `orkestra devam` | Qwen'in istediği komutları (NEEDS) çalıştırdıktan sonra görevi sürdürür |
| `yeni-proje -t python ad` | Kalıptan yeni proje klasörü + git deposu + ilk commit |
| `kalip-ekle -t python` | Bulunduğun projeye kalıbı ekler, var olan dosyalara dokunmaz |
| `qwen-guvenli` | Qwen Code'u güvenlik kontrolleriyle açar |
| `qwen-sunucu [baslat\|dur\|durum\|log]` | `llama-qwen` servisini yönetir (Qwen Code ve dock simgesi aynı sunucuyu kullanır, port 8091) |
| `llama-servis-ayarla` | Servis dosyasını ve dock başlatıcısını kalıp ayarlarıyla yazar, eskilerini yedekler |
| `llama-guncelle` | llama.cpp'yi günceller ve CUDA ile yeniden derler (sonra `llama-servis-ayarla`) |

Dock penceresi kapanınca sunucu yalnızca Qwen Code tarafı kullanmıyorsa kapanır.
`qwen-sunucu` ve `qwen-guvenli` "kullanıyorum" kilidi koyar; `qwen-sunucu dur` kaldırır ve sunucuyu kapatır.

Tipler: `python`, `c-cpp`, `genel`. Yeni tip eklemek için `paketler/` altına klasör aç.

## Projede ne oluşur
| Dosya | Kim okur | Ne zaman |
|---|---|---|
| `AGENTS.md` | Qwen, Codex (doğrudan), Claude (`CLAUDE.md` ile), Gemini (`GEMINI.md` ile) | Her oturumda otomatik |
| `.qwen/skills/*/SKILL.md` | Qwen | Görev tipine göre, orkestratör prompt'a ekler (sandbox açıkken Qwen'in skill aracı çalışmıyor) |
| `docs/ARCHITECTURE.md` | Tüm modeller | Gerektiğinde |
| `docs/TASKS.md` | Orkestratör | Her görevde, yalnızca ilgili görev |
| `docs/STATUS.md` | Orkestratör yazar, sen okursun | Her görevden sonra |
| `.kalip/kontroller.toml` | Orkestratör | Her görevden sonra (lint/test komutları) |
| `.qwen/settings.json` | Qwen | Qwen'in shell aracı tamamen kapalı |

Kullanıcı ayarı `~/.qwen/settings.json` (kur.fish yazar): model bağlantısı, örnekleme ayarları,
sandbox, arka plan hafıza/dream çağrıları kapalı, Qwen Code'un hazır skill'leri kapalı.

## Orkestra nasıl çalışır
1. Sıradaki `durum: bekliyor` görevi alır. Önündeki görev `basarisiz` ise durur
   (sonraki görevler ona bağlı olabilir): yeniden denemek için `bekliyor`, geçmek için `atla` yaz.
2. Qwen'i yeni, temiz bir oturumda açar: yalnızca o görevin metni + `[skills]`'te o tip için
   seçilen skill'ler. Qwen'in her adımı ekranda görünür.
3. `[kontroller]`'deki komutları ağsız, ev klasörünü görmeyen bir bubblewrap kutusunda çalıştırır.
4. Geçerse: TASKS.md'de `durum: tamam`, STATUS.md'ye satır, commit.
   Geçmezse: hata çıktısı Qwen'e verilir, `max_deneme`'ye kadar yeniden dener.
   Deneme hakkı biterse: değişiklikler `.kalip/calisma/*.patch`'e kaydedilip geri alınır.
5. Qwen bir komut isterse (NEEDS) durur ve komutu sana gösterir.

Kayıtlar: `.kalip/calisma/log/` (Qwen'in her oturumu ve kontrol çıktıları, git'e girmez).
Örnek görev listesi: `~/.local/share/qwen-kalip/ornekler/todo/docs/`.

## Güvenlik katmanları
1. **Sandbox (bubblewrap):** `~/.qwen/settings.json` içindeki `tools.executionSandbox`. Qwen yalnızca
   bulunduğu proje klasörüne yazabilir; dışarısı salt okunur. Bu ayar kullanıcı seviyesinde olduğu için
   bir projenin kendi ayar dosyası onu kapatamaz. Model trafiği sandbox dışında kalır.
2. **Komut çalıştıran araçlar kapalı:** `run_shell_command`, `monitor` (arka planda komut çalıştırır),
   `agent` (alt ajan) ve `task_stop` araç listesinden tamamen çıkarıldı. Kullanıcı seviyesinde olduğu için
   hiçbir proje bunları geri açamaz. Qwen'e kalan araçlar: read_file, list_directory, glob, write_file, edit.
2b. **Korunan dosyalar:** `.git/`, `.qwen/`, `.kalip/` ve `.env*` dosyalarına yazma yasak (`permissions.deny`).
   Neden: `.git/config` ya da `.git/hooks` içine yazılan bir komut, sen `git status`/`git commit`
   dediğinde sandbox DIŞINDA çalışır; `.qwen/` içine yazılan ayarlar bir sonraki oturumda komut başlatabilir.
   `qwen-guvenli` ayrıca oturumdan sonra `.git/config` ve `.git/hooks`'u kontrol eder, değiştiyse geri alır.
3. **Kontroller konteynerde:** Testleri orkestratör, ağsız ve yalnızca proje klasörünü gören bir konteynerde çalıştırır. Qwen'in yazdığı kod da bilgisayarına dokunamaz.
4. **Git:** Her görev ayrı commit. Bir şey bozulursa `git restore .` ya da `git reset --hard HEAD` ile geri dönülür.
5. **qwen-guvenli:** yolo modunu reddeder, ev klasöründe açılmaz, git olmayan klasörde açılmaz, commit edilmemiş değişiklik varsa uyarır.
