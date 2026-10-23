function qwen-sunucu --description "Model sunucusunu (llama-qwen servisi) yönetir: başlat, dur, durum, log"
    set -l port (__qwen_port)
    set -l kilit ~/.cache/qwen-kalip/sunucu-kullaniliyor

    if not systemctl --user cat llama-qwen >/dev/null 2>&1
        echo "llama-qwen servisi yok. Oluşturmak için: llama-servis-ayarla" >&2
        return 1
    end

    switch "$argv[1]"
        case '' baslat
            # Kilit: dock penceresi kapanınca sunucu kapanmasın (Qwen Code kullanıyor)
            mkdir -p (path dirname $kilit)
            touch $kilit
            systemctl --user start llama-qwen
            or return 1
            echo -n "Model yükleniyor"
            for i in (seq 600)
                if curl -sf http://127.0.0.1:$port/health | string match -q '*ok*'
                    echo " hazır (port $port)."
                    return 0
                end
                if not systemctl --user is-active --quiet llama-qwen
                    echo
                    echo "Servis durdu. Hatanın ne olduğunu görmek için: qwen-sunucu log" >&2
                    command rm -f -- $kilit
                    return 1
                end
                echo -n .
                sleep 1
            end
            echo
            echo "10 dakikada hazır olmadı. Bakmak için: qwen-sunucu log" >&2
            return 1

        case dur
            command rm -f -- $kilit
            systemctl --user stop llama-qwen
            and echo "Sunucu durduruldu."

        case durum
            if systemctl --user is-active --quiet llama-qwen
                if curl -sf http://127.0.0.1:$port/health | string match -q '*ok*'
                    echo "Çalışıyor, hazır (port $port)."
                else
                    echo "Çalışıyor, model henüz yükleniyor."
                end
            else
                echo "Kapalı."
            end
            test -e $kilit; and echo "Qwen Code tarafı kullanıyor: dock penceresi kapanınca kapanmaz."

        case log
            journalctl --user -u llama-qwen -n 60 -f

        case '*'
            echo "Kullanım: qwen-sunucu [baslat|dur|durum|log]"
            return 1
    end
end
