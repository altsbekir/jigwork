#!/usr/bin/env bash
# End-to-end test of the legacy orchestrator (legacy/qwen-kalip/orkestra/orkestra.py)
# with the real Qwen Code CLI and a scripted fake model (task_model.py).
#
#   bash tests/legacy/orchestrator_e2e.sh        (KEEP_WORK=1 keeps the temp dir)
#
# Scenario (example todo project, 4 tasks + 1 added later):
#   T1  first attempt has a bug, fix attempt repairs it         -> done after 2 attempts
#       also tries to write .git/hooks and AGENTS.md            -> both refused
#   T2  unsorted imports (auto-fix step), report says needs ["none"] -> done in 1 attempt
#       its test tries to escape the check box                  -> secret hidden, no network, .git read-only
#   T3  asks the user to run a command (NEEDS)                  -> stops with exit code 2
#       'resume' runs the checks and continues                  -> done
#   T4  plain-text report instead of structured_output; never compiles -> failed after 3, patch saved, reset
#   T5  added after T4 failed                                   -> run refuses until T4 is retried or skipped
#
# Needs: fish, qwen (Qwen Code), bwrap, git, python3, curl, internet once (pip installs pytest+ruff).

source "$(dirname "$0")/lib.sh"
require fish qwen bwrap git python3 curl

export PORT="$(free_port)"
new_home
trap cleanup EXIT
mkdir -p "$HOME/gizli" && echo "secret" >"$HOME/gizli/anahtar"

mkdir -p "$HOME/Projeler" && cd "$HOME/Projeler"
fish -c 'yeni-proje -t python deneme' >/dev/null
cd deneme
export PROJ="$PWD"
cp "$HOME/.local/share/qwen-kalip/ornekler/todo/docs/"*.md docs/
git add -A && git commit -qm "todo tasks"

start_server "$LEGACY_TESTS/task_model.py" "$WORK/model.log"
ORK="$HOME/.local/share/qwen-kalip/orkestra/orkestra.py"
ork() { python3 "$ORK" "$@" >"$WORK/out.txt" 2>&1; RC=$?; cat "$WORK/out.txt" >>"$WORK/all-output.txt"; }
out_has() { grep -qF -- "$1" "$WORK/out.txt"; }

echo "1. orkestra: T1 (fix loop), T2 (auto-fix), T3 stops on NEEDS"
ork
check "exit code 2 (stopped for NEEDS)" test "$RC" -eq 2
check "T1 done after 2 attempts" out_has "T1 tamam (2. deneme"
check "T2 done in 1 attempt" out_has "T2 tamam (1. deneme"
check "auto-fix step ran" out_has "otomatik düzeltme uygulandı"
check "NEEDS command shown" out_has "pip install rich"
check "needs [\"none\"] did not stop T2" bash -c "[ \"$(grep -c 'çalıştırman gereken' "$WORK/out.txt")\" = 1 ]"
check "AGENTS.md untouched by the model" bash -c "head -1 AGENTS.md | grep -q '^# Project: deneme'"
check "no git hook written by the model" bash -c "! ls .git/hooks | grep -qv sample"
REPORT="$(cat kacis_raporu.txt 2>/dev/null)"
echo "  escape report from inside the check box: $REPORT"
check "box: secret in real home not readable" bash -c "grep -q sir-okunamadi <<<'$REPORT'"
check "box: no network" bash -c "grep -q ag-kapali <<<'$REPORT'"
check "box: .git read-only" bash -c "grep -q git-korundu <<<'$REPORT'"
check "box: nothing written to the real home" test ! -e "$HOME/KACIS.txt"
check "fix prompt sent for T1 with the pytest failure" grep -q "Fix attempt 2 for task T1.*test_parse_done" "$WORK/model.log"
check "prompt marks new files" grep -q "src/todo/storage.py (new, create it)" "$WORK/model.log"

echo "2. orkestra while a task is half-done"
ork
check "refuses to start" test "$RC" -eq 1
check "says to resume" out_has "orkestra devam"

echo "3. orkestra devam: T3 checks, then T4 fails 3 times"
ork devam
check "exit code 1 (T4 failed)" test "$RC" -eq 1
check "T3 done" out_has "T3 tamam"
check "T4 plain-text report was parsed" out_has "Rapor: CLI yazıldı."
check "T4 failed after 3 attempts" out_has "T4 başarısız"
check "failed attempt saved as a patch" bash -c "ls .kalip/calisma/T4-basarisiz-*.patch"
check "working tree clean after failure" bash -c "[ -z \"\$(git status --porcelain)\" ]"
check "STATUS.md has 4 rows" bash -c "[ \"\$(grep -c '^| 20' docs/STATUS.md)\" = 4 ]"

check "TASKS.md: T4 marked basarisiz" grep -q "durum: basarisiz" docs/TASKS.md

echo "4. a later task does not run while T4 is failed"
printf '\n## T5: Extra\ndurum: bekliyor\ntip: dokuman\ndosyalar: README.md\ngorev: Write a README.\nkabul:\n- README exists\n' >>docs/TASKS.md
git commit -qam "add T5"
ork
check "refuses to skip a failed task" out_has "'basarisiz' durumda"
sed -i '/## T4/,/^durum/ s/^durum: basarisiz/durum: atla/' docs/TASKS.md
git commit -qam "skip T4"
ork durum
check "after 'atla', T5 is next and pending" out_has "T5   bekliyor"

stop_server
summary
