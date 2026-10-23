function llama-guncelle --description "llama.cpp'yi günceller ve CUDA desteğiyle yeniden derler"
    set -l dizin ~/llama.cpp
    set -q LLAMA_DIZINI; and set dizin $LLAMA_DIZINI

    if not test -d $dizin/.git
        echo "$dizin bir git klonu değil. Temiz kurulum için:" >&2
        echo "  git clone https://github.com/ggml-org/llama.cpp ~/llama.cpp" >&2
        return 1
    end

    # CUDA derleyicisi (Arch'ta /opt/cuda; fish profile.d dosyalarını okumadığı için elle ekliyoruz)
    if not command -q nvcc; and test -x /opt/cuda/bin/nvcc
        set -gx PATH /opt/cuda/bin $PATH
    end
    if not command -q nvcc
        echo "CUDA toolkit yok. Kur:  sudo pacman -S cuda   (sonra tekrar: llama-guncelle)" >&2
        return 1
    end

    # Arch'ın cuda paketi uyumlu GCC sürümünü NVCC_CCBIN ile belirtir
    set -l cmake_ek
    if test -f /etc/profile.d/cuda.sh
        set -l ccbin (string match -rg "NVCC_CCBIN=['\"]?([^'\" ]+)" < /etc/profile.d/cuda.sh)
        if test -n "$ccbin"
            set cmake_ek -DCMAKE_CUDA_HOST_COMPILER=$ccbin
        end
    end

    echo "==> Kaynak güncelleniyor"
    git -C $dizin pull --ff-only
    or begin
        echo "git pull başarısız (klasörde elle değişiklik olabilir). Çıktıyı gönder." >&2
        return 1
    end

    echo "==> Derleniyor (CUDA ile, 10-20 dakika sürebilir)"
    cmake -S $dizin -B $dizin/build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release $cmake_ek
    or return 1
    cmake --build $dizin/build --config Release -j (nproc) --target llama-server llama-cli llama-bench
    or return 1

    echo "==> Bitti"
    $dizin/build/bin/llama-server --version 2>&1 | tail -n 2
    $dizin/build/bin/llama-server --list-devices 2>&1 | tail -n 3
    echo
    echo "Servisi yeni sürüme göre ayarlamak için: llama-servis-ayarla"
end
