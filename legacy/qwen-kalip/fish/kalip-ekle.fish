function kalip-ekle --description "Var olan bir projeye Qwen kalıbını ekler; mevcut dosyaların üzerine yazmaz"
    argparse h/help 't/tip=' -- $argv
    or return 1

    set -l kalip (__qwen_kalip_dizini)

    if set -q _flag_help; or test (count $argv) -gt 1
        echo "Kullanım: kalip-ekle [-t TİP] [klasör]   (klasör verilmezse bulunduğun klasör)"
        return 1
    end

    set -l hedef (pwd)
    test (count $argv) -eq 1; and set hedef (path resolve $argv[1])
    set -l tip genel
    set -q _flag_tip; and set tip $_flag_tip

    if test "$hedef" = (path resolve ~); or test "$hedef" = /
        echo "Ev klasörüne ya da köke kalıp eklemiyorum. Proje klasörüne geç." >&2
        return 1
    end
    if not test -d $hedef
        echo "Klasör yok: $hedef" >&2
        return 1
    end
    if not test -d $kalip/paketler/$tip
        echo "Bilinmeyen tip: $tip. Seçenekler: "(string join ', ' (path basename $kalip/paketler/*)) >&2
        return 1
    end

    # Hangi dosyalar zaten var? (bunlara dokunulmayacak)
    set -l atlanan
    for kaynak in $kalip/paketler/$tip $kalip/ortak
        for f in (find $kaynak -type f -printf '%P\n')
            if test -e $hedef/$f; and not contains -- $f $atlanan
                set -a atlanan $f
            end
        end
    end

    set -l agents_yeni 1
    test -e $hedef/AGENTS.md; and set agents_yeni 0

    # Önce paket, sonra ortak: paket dosyaları öncelikli, mevcut dosyalar korunur
    cp -a --update=none $kalip/paketler/$tip/. $hedef/
    cp -a --update=none $kalip/ortak/. $hedef/
    __qwen_kalip_birlestir $hedef (path basename $hedef) $tip $agents_yeni

    echo "✔ Kalıp eklendi (tip: $tip). Hiçbir mevcut dosyanın üzerine yazılmadı."
    if test (count $atlanan) -gt 0
        echo "  Zaten var olduğu için atlananlar:"
        printf '    - %s\n' $atlanan
    end
    echo "  Değişiklikleri gözden geçir ve commit at:  git status"
end
