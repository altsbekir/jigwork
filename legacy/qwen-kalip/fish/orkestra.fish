function orkestra --description "docs/TASKS.md'deki görevleri yerel Qwen ile tek tek uygular (yardım: orkestra yardim)"
    set -l betik (__qwen_kalip_dizini)/orkestra/orkestra.py
    if not test -f $betik
        echo "orkestra.py bulunamadı. Kalıp klasöründe: fish kur.fish" >&2
        return 1
    end

    # Model gerektiren komutlarda sunucuyu hazırla ve "kullanıyorum" kilidini koy
    switch "$argv[1]"
        case '' tek devam calistir
            if not curl -sf http://127.0.0.1:(__qwen_port)/health | string match -q '*ok*'
                qwen-sunucu baslat
                or return 1
            end
            mkdir -p ~/.cache/qwen-kalip
            touch ~/.cache/qwen-kalip/sunucu-kullaniliyor
    end

    python3 $betik $argv
end
