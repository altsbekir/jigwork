function __qwen_kalip_dizini --description "Kalıbın kurulu olduğu klasörü yazdırır"
    if set -q QWEN_KALIP_DIZINI
        echo $QWEN_KALIP_DIZINI
    else
        echo ~/.local/share/qwen-kalip
    end
end
