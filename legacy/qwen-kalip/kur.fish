#!/usr/bin/env fish
# Qwen proje kalıbını kurar / günceller.
# Kullanım:  fish kur.fish

set -l kaynak (path dirname (path resolve (status filename)))
set -l hedef ~/.local/share/qwen-kalip
set -l fonk ~/.config/fish/functions

mkdir -p $hedef $fonk
command rm -rf -- $hedef/ortak $hedef/paketler $hedef/ayarlar $hedef/orkestra $hedef/ornekler
cp -a $kaynak/ortak $kaynak/paketler $kaynak/ayarlar $kaynak/orkestra $kaynak/ornekler $hedef/
cp $kaynak/KULLANIM.md $hedef/
cp $kaynak/fish/*.fish $fonk/

echo "✔ Kalıp kuruldu: $hedef"
echo "✔ Fish komutları eklendi: yeni-proje, kalip-ekle, orkestra, qwen-guvenli, qwen-sunucu, llama-servis-ayarla, llama-guncelle"

# Qwen Code kullanıcı ayarı (model bağlantısı, örnekleme, sandbox, hafıza kapalı)
mkdir -p ~/.qwen
if test -e ~/.qwen/settings.json
    set -l yedek ~/.qwen/settings.json.yedek-(date +%Y%m%d-%H%M%S)
    cp ~/.qwen/settings.json $yedek
    if python3 $kaynak/ayarlar/birlestir.py ~/.qwen/settings.json $kaynak/ayarlar/qwen-settings.json
        echo "✔ ~/.qwen/settings.json güncellendi (eski hali: $yedek)"
    end
else
    cp $kaynak/ayarlar/qwen-settings.json ~/.qwen/settings.json
    echo "✔ Qwen Code ayarı yazıldı: ~/.qwen/settings.json"
end

if not command -q bwrap
    echo
    echo "! Sandbox için bubblewrap gerekli:  sudo pacman -S bubblewrap"
end

echo
echo "Yeni bir fish penceresi aç (ya da: exec fish)."
echo "Model servisini kalıp ayarlarıyla yazmak için (bir kez): llama-servis-ayarla"
