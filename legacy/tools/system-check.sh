#!/usr/bin/env bash
# Sistem ve yerel LLM kurulum kontrolü (CachyOS / Arch)
# Kullanım: bash sistem-kontrol.sh
# Not: RAM hızını okumak için sudo şifresi istenebilir.

baslik() { printf '\n===== %s =====\n' "$1"; }

baslik "İŞLEMCİ"
lscpu | grep -E '^(Model name|Model adı|CPU\(s\)|Thread\(s\) per core|Core\(s\) per socket|CPU max MHz)' 
printf 'AVX2: '; grep -q avx2 /proc/cpuinfo && echo var || echo yok
printf 'AVX512: '; grep -q avx512f /proc/cpuinfo && echo var || echo yok

baslik "RAM"
free -h
if command -v dmidecode >/dev/null 2>&1; then
  echo "-- RAM modülleri (sudo gerekli) --"
  sudo dmidecode -t memory 2>/dev/null \
    | grep -E '^\s*(Size|Type|Speed|Configured Memory Speed|Configured Clock Speed):' \
    | grep -v 'No Module Installed' | sort | uniq -c
else
  echo "dmidecode kurulu değil -> sudo pacman -S dmidecode"
fi

baslik "GPU"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total,memory.used,driver_version --format=csv
  nvidia-smi | grep -i 'CUDA Version' || true
else
  echo "nvidia-smi bulunamadı"
fi

baslik "LLAMA.CPP"
for bin in llama-server llama-cli; do
  if command -v "$bin" >/dev/null 2>&1; then
    echo "$bin: $(command -v "$bin")"
  fi
done
if command -v llama-server >/dev/null 2>&1; then
  llama-server --version 2>&1 | tail -n 3
fi
echo "-- pacman paketleri --"
pacman -Qs llama 2>/dev/null | grep -i '^local' || echo "(pacman'de llama paketi yok)"
echo "-- Elle derlenmiş olabilecek yerler --"
for d in ~/llama.cpp ~/Projeler/llama.cpp ~/src/llama.cpp /opt/llama.cpp; do
  [ -d "$d" ] && echo "bulundu: $d" && ls "$d"/build/bin 2>/dev/null | grep -E '^llama-(server|cli)$'
done

baslik "GGUF MODEL DOSYALARI (500MB üstü)"
find ~ /opt /mnt /media -iname '*.gguf' -size +500M 2>/dev/null \
  -exec du -h {} + | sort -h

baslik "DİĞER ÇALIŞTIRICILAR"
if command -v ollama >/dev/null 2>&1; then echo "-- ollama --"; ollama list 2>&1; fi
[ -d ~/.lmstudio/models ] && echo "LM Studio model klasörü var: ~/.lmstudio/models"
echo "-- Şu an 8080/11434 portunu dinleyen var mı? --"
ss -ltnp 2>/dev/null | grep -E ':(8080|11434)\b' || echo "(yok)"

baslik "ARAÇLAR"
for t in node npm qwen git python3 pytest ruff; do
  if command -v "$t" >/dev/null 2>&1; then
    printf '%-8s %s\n' "$t" "$("$t" --version 2>&1 | head -n1)"
  else
    printf '%-8s YOK\n' "$t"
  fi
done

baslik "DİSK"
df -h ~ | tail -n1

echo
echo "Bitti. Yukarıdaki çıktının tamamını kopyalayıp gönderebilirsin."
