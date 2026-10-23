function __qwen_kalip_birlestir --description "Kalıp parçalarını projede birleştirir (iç yardımcı)" --argument-names hedef ad tip agents_yeni
    # Paketin AGENTS.md ekini, yalnızca AGENTS.md'yi kalıp oluşturduysa ekle
    set -l ek $hedef/.kalip/AGENTS.ek.md
    if test -f $ek
        if test "$agents_yeni" = 1
            cat $ek >>$hedef/AGENTS.md
            command rm -f -- $ek
        else
            echo "Not: AGENTS.md zaten vardı, dokunmadım. Pakete özel satırlar şurada: .kalip/AGENTS.ek.md"
        end
    end

    # .gitignore: ortak + paket satırlarından eksik olanları ekle (tekrar eklemez)
    set -l gi $hedef/.gitignore
    touch $gi
    set -l eklenecek
    for kaynak in (__qwen_kalip_dizini)/ortak/.gitignore $hedef/.kalip/gitignore.ek
        test -f $kaynak; or continue
        for satir in (cat $kaynak)
            if test -z "$satir"; or string match -q '#*' -- $satir
                continue
            end
            if not grep -qxF -- $satir $gi; and not contains -- $satir $eklenecek
                set -a eklenecek $satir
            end
        end
    end
    if test (count $eklenecek) -gt 0
        printf '\n# kalıp (%s)\n' $tip >>$gi
        printf '%s\n' $eklenecek >>$gi
    end
    command rm -f -- $hedef/.kalip/gitignore.ek

    # {{PROJE_ADI}} yer tutucusunu doldur (.git hariç)
    for f in (grep -rlF --exclude-dir=.git '{{PROJE_ADI}}' $hedef)
        sed -i "s/{{PROJE_ADI}}/$ad/g" $f
    end

    mkdir -p $hedef/.kalip
    echo $tip >$hedef/.kalip/tip
end
