function qwen-guvenli --description "Qwen Code'u güvenlik kontrolleriyle başlatır"
    # 1) Onaysız her şeyi çalıştıran modları reddet
    for a in $argv
        switch $a
            case -y --yolo --approval-mode=yolo
                echo "Bu kurulumda yolo modu kapalı." >&2
                return 1
        end
    end
    if contains -- yolo $argv
        echo "Bu kurulumda yolo modu kapalı." >&2
        return 1
    end

    # 2) Sandbox ayarı ve bubblewrap yerinde mi?
    if not command -q bwrap
        echo "bubblewrap kurulu değil, sandbox çalışmaz. Kur:  sudo pacman -S bubblewrap" >&2
        return 1
    end
    set -l ayar (cat ~/.qwen/settings.json 2>/dev/null | string collect)
    if not string match -q '*executionSandbox*' -- $ayar; or not string match -q '*"monitor"*' -- $ayar; or not string match -q '*Edit(.git/\*\*)*' -- $ayar
        echo "~/.qwen/settings.json içinde güvenlik ayarları eksik. Kalıp klasöründe tekrar: fish kur.fish" >&2
        return 1
    end

    # 3) Yanlış klasörde açılmasın
    set -l burasi (pwd)
    if test "$burasi" = (path resolve ~); or test "$burasi" = /
        echo "Ev klasöründe ya da kökte açmıyorum. Önce proje klasörüne geç." >&2
        return 1
    end

    # 4) Git güvenlik ağı: her şey geri alınabilir olsun
    if not git rev-parse --is-inside-work-tree >/dev/null 2>&1
        echo "Burası bir git deposu değil; geri alma imkânı olmadan açmıyorum." >&2
        echo "Yeni proje için: yeni-proje <ad>   |   var olan için: git init; and kalip-ekle" >&2
        return 1
    end
    set -l kirli (git status --porcelain)
    if test (count $kirli) -gt 0
        echo "Commit edilmemiş değişiklikler var. Qwen bir şeyi bozarsa bunlar karışabilir:"
        printf '  %s\n' $kirli[1..5]
        read -l -P "Yine de devam edilsin mi? [e/H] " cevap
        if not string match -qi e -- $cevap
            echo "Vazgeçildi. Önce:  git add -A; and git commit -m 'kayıt'"
            return 1
        end
    end
    if not test -f AGENTS.md
        echo "Uyarı: AGENTS.md yok. Kalıp eklemek için: kalip-ekle"
    end

    # 5) Model sunucusu açık mı?
    if not curl -sf http://127.0.0.1:(__qwen_port)/health | string match -q '*ok*'
        echo "Model sunucusu hazır değil, başlatılıyor..."
        qwen-sunucu baslat
        or return 1
    else
        # Sunucu dock'tan açılmış olabilir: pencere kapanınca kapanmasın
        mkdir -p ~/.cache/qwen-kalip
        touch ~/.cache/qwen-kalip/sunucu-kullaniliyor
    end

    # 6) .git koruması: Qwen proje klasörüne yazabildiği için .git/hooks ya da .git/config'e
    #    bir komut gizleyebilir; sen sonra "git commit" dediğinde o komut sandbox DIŞINDA çalışır.
    #    Oturumdan önce kopyala, sonra karşılaştır.
    set -l gitdir (git rev-parse --absolute-git-dir)
    set -l yedek (mktemp -d)
    cp -a $gitdir/config $gitdir/hooks $yedek/ 2>/dev/null

    command qwen $argv
    set -l durum $status

    set -l fark (diff -r $yedek/config $gitdir/config 2>&1; diff -r $yedek/hooks $gitdir/hooks 2>&1)
    if test (count $fark) -gt 0
        echo
        set_color red
        echo "!!! DİKKAT: Oturum sırasında .git/config ya da .git/hooks değişti."
        echo "!!! Bu dosyalar git komutlarında sandbox dışında komut çalıştırabilir."
        set_color normal
        printf '  %s\n' $fark[1..20]
        read -l -P "Eski haline döndürülsün mü? [E/h] " cevap
        if not string match -qi h -- $cevap
            cp -a $yedek/config $gitdir/config
            command rm -rf -- $gitdir/hooks
            cp -a $yedek/hooks $gitdir/hooks
            echo "✔ .git/config ve .git/hooks eski haline döndürüldü."
        else
            echo "Dokunulmadı. git komutu çalıştırmadan önce mutlaka incele: $gitdir"
        end
    end
    command rm -rf -- $yedek
    return $durum
end
