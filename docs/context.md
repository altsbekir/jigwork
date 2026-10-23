# Context: how jigwork came to be

This file hands over a long design-and-test conversation (October 2026) so a new session can
continue without it. Read it once, fully.

## The user's goal
Use a free, fully local model for real coding work, and see how far a small model can go with a
carefully built workflow. Planning with large models (Claude/GPT) is an accepted later option;
the current experiment is "fully local".

## The user's machine (the reference setup)
| | |
|---|---|
| OS | CachyOS (Arch based), KDE Plasma, Konsole, **fish** shell |
| CPU | Intel i7-12700H (6 performance cores, AVX2, no AVX-512) |
| RAM | 32 GB DDR4-3200, dual channel |
| GPU | NVIDIA RTX 4060 Laptop, 8 GB (about 1 GB used by the desktop) |
| Model | `~/models/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf` (21 GB, Unsloth) |
| Inference | llama.cpp built from source in `~/llama.cpp` (CUDA), run as systemd **user** service `llama-qwen` on port **8091** |
| Agent | Qwen Code 0.26 (npm, prefix `~/.local`) |
| Other | Python 3.14, git 2.56, Node via pacman, bubblewrap |

The user also has a desktop launcher (dock icon) that starts `llama-qwen` and opens the
llama.cpp web UI in a Brave app window; closing the window stops the server unless jigwork is
using it (lock file `~/.cache/qwen-kalip/sunucu-kullaniliyor`). That launcher is personal; it
belongs in `examples/`, not in the core.

Measured: **20–21 tokens/s** generation with the service settings below.

## What exists today (legacy v0, `legacy/qwen-kalip/`)
Installed with `fish kur.fish` into `~/.local/share/qwen-kalip` + fish functions:

| Legacy command | Purpose | New name (planned) |
|---|---|---|
| `yeni-proje -t python X`, `kalip-ekle` | create / adopt a project from the template | `jigw init` |
| `orkestra [tek\|durum\|kontrol\|devam]` | the task loop (`orkestra/orkestra.py`) | `jigw run/status/check/resume` |
| `qwen-guvenli` | interactive Qwen Code with safety checks + .git guard | `jigw chat` |
| `qwen-sunucu [baslat\|dur\|durum\|log]` | manage the `llama-qwen` service | `jigw server ...` |
| `llama-servis-ayarla` | write the systemd unit + launcher from settings | `jigw server setup` |
| `llama-guncelle` | git pull + CUDA build of llama.cpp | `jigw server build` |
| `kur.fish` + `ayarlar/birlestir.py` | install, merge `~/.qwen/settings.json` (backup first) | `jigw setup` |
| `legacy/tools/system-check.sh` | hardware / install report | `jigw doctor` |

Project layout produced by the template (Turkish names, to be renamed):
`AGENTS.md` (+ `CLAUDE.md`/`GEMINI.md` importing it), `docs/ARCHITECTURE.md`, `docs/TASKS.md`,
`docs/STATUS.md`, `.qwen/settings.json`, `.qwen/skills/*/SKILL.md`, `.kalip/kontroller.toml`
(checks, auto-fix, skills per task type, limits), `.kalip/calisma/` (logs, patches; gitignored).

### The task loop (orkestra.py)
1. Refuse to start on a dirty tree, a half-done task, or a failed task ahead in the queue.
2. Next `durum: bekliyor` task → prompt = task + files marked `(exists)`/`(new, create it)` +
   acceptance criteria + "how to work" rules + skill bodies for the task type (inlined, because
   the skill tool does not work under the execution sandbox).
3. `qwen "<prompt>" --approval-mode auto-edit --output-format stream-json --json-schema @schema
   --max-wall-time 45m --max-tool-calls 80`; progress lines printed from the event stream.
   Report = `structured_output` {changed, done, needs, doubts}; plain-text fallback parser.
4. Snapshot/compare `.git/config` + hooks around the run; restore protected files if touched.
5. `needs` non-empty → stop, show commands, save `yarim.json`; `orkestra devam` resumes.
6. Auto-fix in the box (`ruff format` + `ruff check --fix`), then checks in the box, stop at the
   first failing check. Fail → fix prompt with trimmed output + `fix-failing-checks` skill, up to
   `max_deneme` (3). Pass → TASKS `tamam`, STATUS row, commit. Out of attempts → patch to
   `.kalip/calisma/`, `git reset --hard`, mark `basarisiz`, commit the status change.
7. Python test env: venv outside the project (`~/.cache/qwen-kalip/venv/<name>-<hash>`) with
   pytest, ruff, and `[project].dependencies`; rebuilt when the dependency list changes.

### llama.cpp service settings (proven)
```
llama-server -m <model> --alias qwen3.6-35b-a3b --host 127.0.0.1 --port 8091
  -c 65536 -np 1 --fit on --fit-target 1024
  -fa on --cache-type-k q8_0 --cache-type-v q8_0 --jinja
  -t 6 --cache-ram 2048
  --temp 0.6 --top-p 0.95 --top-k 20 --min-p 0 --presence-penalty 0
```
Old llama.cpp without `--fit`: fall back to `-ngl 99 --cpu-moe`.

## What is proven
- Security probes and orchestrator e2e: `tests/legacy/` (all green on Qwen Code 0.26.0).
- Real model, real project: `docs/bench-results.md`.

## What is NOT done yet
Everything in `docs/roadmap.md`: the package, English names, i18n, cross-platform, doctor,
bench, macOS, container isolation, other agents/servers.
