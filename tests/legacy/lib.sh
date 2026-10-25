# Shared helpers for the legacy test scripts. Source it, do not run it.
#
# Every test runs with a throw-away HOME, so it never reads or changes the real
# ~/.qwen, ~/.config/fish, ~/.cache or the real llama.cpp server. Fake model servers
# listen on a free port, never on the real one (8091).

set -u
LEGACY_TESTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$LEGACY_TESTS/../.." && pwd)"
LEGACY="$REPO/legacy/qwen-kalip"

PASS=0
FAIL=0
pass() { printf '  \033[32mPASS\033[0m %s\n' "$1"; PASS=$((PASS + 1)); }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAIL=$((FAIL + 1)); }
check() { # check "description" command...
    local desc="$1"; shift
    if "$@" >/dev/null 2>&1; then pass "$desc"; else fail "$desc"; fi
}
summary() {
    echo
    echo "passed: $PASS  failed: $FAIL"
    [ "$FAIL" -eq 0 ]
}

require() {
    for c in "$@"; do
        command -v "$c" >/dev/null 2>&1 || { echo "missing required command: $c" >&2; exit 2; }
    done
}

free_port() {
    python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])'
}

# new_home: create a fresh HOME, install the legacy kit into it, point Qwen Code at $PORT.
new_home() {
    WORK="$(mktemp -d "${TMPDIR:-/tmp}/jigwork-test.XXXXXX")"
    export HOME="$WORK/home"
    # fish, git and the kit follow XDG_* before HOME (set on CI runners): drop them, or the
    # kit is installed into, and read from, the real config/data/cache dirs
    unset XDG_CONFIG_HOME XDG_DATA_HOME XDG_CACHE_HOME XDG_STATE_HOME
    mkdir -p "$HOME"
    git config --global user.name "jigwork test"
    git config --global user.email "test@example.invalid"
    git config --global init.defaultBranch master
    fish "$LEGACY/kur.fish" >/dev/null
    python3 - "$HOME/.qwen/settings.json" "$PORT" <<'EOF'
import json, sys
path, port = sys.argv[1], sys.argv[2]
s = json.load(open(path))
s["modelProviders"]["openai"][0]["baseUrl"] = f"http://127.0.0.1:{port}/v1"
json.dump(s, open(path, "w"), indent=2)
EOF
}

SERVER_PID=""
start_server() { # start_server script.py args...
    python3 "$@" &
    SERVER_PID=$!
    for _ in $(seq 50); do
        curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && return 0
        sleep 0.1
    done
    echo "fake server did not start" >&2
    exit 2
}
stop_server() {
    [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null && wait "$SERVER_PID" 2>/dev/null
    SERVER_PID=""
}

cleanup() {
    stop_server
    if [ -n "${KEEP_WORK:-}" ]; then
        echo "work dir kept: $WORK"
    else
        rm -rf "$WORK"
    fi
}
