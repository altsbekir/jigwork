function llama-servis-ayarla --description "llama-qwen servisini ve dock başlatıcısını kalıbın ayarlarıyla yazar (eskileri yedeklenir)"
    set -l dizin ~/llama.cpp
    set -q LLAMA_DIZINI; and set dizin $LLAMA_DIZINI
    set -l model ~/models/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
    set -q QWEN_MODEL_YOLU; and set model $QWEN_MODEL_YOLU
    set -l ctx 65536
    set -q QWEN_CTX; and set ctx $QWEN_CTX
    set -l port (__qwen_port)
    set -l bin $dizin/build/bin/llama-server
    set -l zaman (date +%Y%m%d-%H%M%S)

    if not test -x $bin
        echo "llama-server bulunamadı: $bin" >&2
        return 1
    end
    if not test -f $model
        echo "Model bulunamadı: $model" >&2
        return 1
    end

    if not $bin --list-devices 2>&1 | string match -qi '*cuda*'
        echo "UYARI: Bu llama.cpp CUDA desteksiz görünüyor; model CPU'da çok yavaş çalışır. Düzeltmek için: llama-guncelle" >&2
    end

    # Bellek yerleşimi: yeni sürümde --fit GPU'yu otomatik doldurur (1 GB pay bırakarak)
    set -l yerlesim
    if $bin --help 2>&1 | string match -q -- '*--fit-target*'
        set yerlesim '--fit on --fit-target 1024'
    else
        echo "Not: llama.cpp sürümün eski (--fit yok); bütün expert katmanları CPU'ya konuyor. Güncellemek için: llama-guncelle" >&2
        set yerlesim '-ngl 99 --cpu-moe'
    end

    # --- servis dosyası ---
    set -l birim ~/.config/systemd/user/llama-qwen.service
    mkdir -p (path dirname $birim)
    if test -e $birim
        cp $birim $birim.yedek-$zaman
        echo "• Eski servis yedeklendi: $birim.yedek-$zaman"
    end
    # Seçenekler:
    #  -c / -np 1        : 64K context, tek istek yuvası (Qwen Code ayarındaki contextWindowSize ile aynı)
    #  q8_0 KV cache     : KV yarı boyutta; kazanılan VRAM'e --fit daha fazla katman koyar
    #  -t 6              : i7-12700H'nin 6 performans çekirdeği
    #  --cache-ram 2048  : tekrar eden prompt başlarını RAM'de tut, 32 GB'ı zorlamadan
    #  örnekleme         : Qwen'in "thinking, precise coding" önerisi (sohbet arayüzü için;
    #                      Qwen Code aynı değerleri kendisi de gönderiyor)
    printf '%s\n' \
        '# qwen-kalip tarafından yazıldı. Yeniden yazmak için: llama-servis-ayarla' \
        '[Unit]' \
        'Description=llama.cpp server - Qwen3.6-35B-A3B' \
        '' \
        '[Service]' \
        "ExecStart=$bin -m $model --alias qwen3.6-35b-a3b \\" \
        "    --host 127.0.0.1 --port $port \\" \
        "    -c $ctx -np 1 $yerlesim \\" \
        "    -fa on --cache-type-k q8_0 --cache-type-v q8_0 --jinja \\" \
        "    -t 6 --cache-ram 2048 \\" \
        '    --temp 0.6 --top-p 0.95 --top-k 20 --min-p 0 --presence-penalty 0' \
        'Restart=on-failure' \
        >$birim
    echo "✔ Servis yazıldı: $birim  (port $port, context $ctx)"

    # --- dock başlatıcısı: yalnızca zaten varsa güncelle ---
    set -l app ~/.local/bin/qwen-app
    set -l yeni_app (__qwen_kalip_dizini)/ayarlar/qwen-app
    if test -e $app
        if not string match -q '*qwen-kalip*' < $app
            cp $app $app.yedek-$zaman
            echo "• Eski qwen-app yedeklendi: $app.yedek-$zaman"
        end
        cp $yeni_app $app
        chmod +x $app
        echo "✔ Dock başlatıcısı güncellendi: pencereyi kapatmak, Qwen Code'un kullandığı sunucuyu artık kapatmaz"
    end

    systemctl --user daemon-reload
    if systemctl --user is-active --quiet llama-qwen
        read -l -P "Servis şu an çalışıyor. Yeni ayarlarla yeniden başlatılsın mı? [e/H] " cevap
        if string match -qi e -- $cevap
            systemctl --user restart llama-qwen
            echo "✔ Yeniden başlatıldı"
        else
            echo "Yeni ayarlar bir sonraki başlatmada geçerli olacak."
        end
    end
end
