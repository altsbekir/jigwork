function __qwen_port --description "Model sunucusunun portu (varsayılan 8091)"
    if set -q QWEN_PORT
        echo $QWEN_PORT
    else
        echo 8091
    end
end
