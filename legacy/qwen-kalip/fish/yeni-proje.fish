function yeni-proje --description "Qwen kalıbıyla yeni bir proje klasörü oluşturur"
    argparse h/help 't/tip=' -- $argv
    or return 1

    set -l kalip (__qwen_kalip_dizini)

    if set -q _flag_help; or test (count $argv) -ne 1
        echo "Kullanım: yeni-proje [-t TİP] <proje-adı>"
        if test -d $kalip/paketler
            echo "Tipler: "(string join ', ' (path basename $kalip/paketler/*))"  (varsayılan: genel)"
        end
        return 1
    end

    set -l ad $argv[1]
    set -l tip genel
    set -q _flag_tip; and set tip $_flag_tip

    if not string match -qr '^[A-Za-z0-9][A-Za-z0-9._-]*$' -- $ad
        echo "Proje adı yalnızca harf, rakam, nokta, alt çizgi ve tire içerebilir." >&2
        return 1
    end
    if not test -d $kalip/ortak
        echo "Kalıp bulunamadı: $kalip  (önce kur.fish çalıştır)" >&2
        return 1
    end
    if not test -d $kalip/paketler/$tip
        echo "Bilinmeyen tip: $tip. Seçenekler: "(string join ', ' (path basename $kalip/paketler/*)) >&2
        return 1
    end
    if test -e $ad
        echo "'$ad' zaten var, üzerine yazmıyorum. Var olan proje için: kalip-ekle" >&2
        return 1
    end

    mkdir -p $ad
    cp -a $kalip/ortak/. $ad/
    cp -a $kalip/paketler/$tip/. $ad/
    __qwen_kalip_birlestir $ad $ad $tip 1

    git -C $ad init -q
    git -C $ad add -A
    if not git -C $ad commit -qm "Proje kalıptan oluşturuldu (tip: $tip)"
        echo "Uyarı: ilk commit atılamadı. Şunları bir kez ayarla:" >&2
        echo "  git config --global user.name 'Adın'" >&2
        echo "  git config --global user.email 'e-postan'" >&2
    end

    echo
    echo "✔ '$ad' oluşturuldu (tip: $tip)."
    echo "  Sıradaki adımlar:"
    echo "  1. docs/ARCHITECTURE.md dosyasını doldur"
    echo "  2. docs/TASKS.md içine küçük görevleri yaz"
    echo "  3. cd $ad; and qwen-guvenli"
end
