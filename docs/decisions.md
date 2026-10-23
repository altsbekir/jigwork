# Decisions

| # | Decision | Why |
|---|---|---|
| 1 | Name **jigwork**, command **`jigw`** (full name `jigwork` also installed) | International audience. A jig guides a tool for accurate, repeatable work: the model is the tool. "kalfa" and "trellis" were dropped (existing projects with the same name). |
| 2 | Repo is **private** until the system has been used on real projects for 1–2 weeks | Needs real-model evidence before public claims. |
| 3 | **English**: code, identifiers, CLI commands (kebab-case subcommands), config keys, commit messages, `docs/`, and everything sent to the model | Contributors and model quality (English prompts are also ~1.5–2x cheaper in tokens than Turkish). |
| 4 | **Bilingual user surface**: CLI messages via an i18n catalog (en, tr); `jigw lang tr|en`; default from `LANG` | The first user and audience are Turkish-speaking; the code stays English. |
| 5 | **Docs split** `docs/en/` + `docs/tr/` for user docs; `README.md` (en) + `README.tr.md` | Same reason. Internal design docs (this folder) are English only. |
| 6 | **Platforms:** Linux first-class; macOS planned (Qwen Code ships seatbelt profiles; our check box needs a `sandbox-exec` backend); **Windows via WSL2** for now | Both security halves (agent sandbox, check box) are Linux/macOS primitives. |
| 7 | **Isolation modes** in config: `native` (today) and `container` (later: agent + checks in Docker/Podman, network only to the model server) | Container mode is the realistic native-Windows path and a uniform option everywhere. Windows Sandbox needs Pro editions; AppContainer would not cover the agent. |
| 8 | All logic in **one Python package**; shells (fish/bash/zsh) get only thin wrappers and completions | Cross-platform and testable; fish code cannot be unit-tested. |
| 9 | **Adapters** for agent (Qwen Code first), model server (llama.cpp, external URL; Ollama/LM Studio later), sandbox (bwrap; seatbelt, container later), project template | Other models and scenarios without touching the core. |
| 10 | Hardware/model **profiles** (`profiles/<model>/<hardware>.toml`) instead of constants | Port, context, threads, offload and sampling are setup-specific. |
| 11 | The project name lives in **one place** in code (package metadata + a constant); project dir `.jigwork/` | Renaming must be cheap. |
| 12 | TASKS.md fields become English (`status`, `type`, `files`, `task`, `acceptance`; statuses `pending`, `done`, `failed`, `skip`); Turkish names stay accepted as aliases; `jigw migrate` converts v0 projects | Existing projects keep working. |
| 13 | **No web tools** for the agent | See findings #7. |
| 14 | Personal launcher (Brave app window) goes to `examples/desktop-launcher/` | Not core. |
| 15 | License: **undecided** (MIT or Apache-2.0 likely) before going public | |

## Command map (planned)
| Command | Replaces |
|---|---|
| `jigw init [--type python\|c-cpp\|generic]` | `yeni-proje`, `kalip-ekle` (empty dir → create; existing → adopt without overwriting) |
| `jigw run [--one]`, `jigw resume`, `jigw status`, `jigw check` | `orkestra`, `orkestra tek/devam/durum/kontrol` |
| `jigw tasks lint` | new: validate TASKS.md before running |
| `jigw chat` | `qwen-guvenli` |
| `jigw server start\|stop\|status\|logs\|setup\|build` | `qwen-sunucu`, `llama-servis-ayarla`, `llama-guncelle` |
| `jigw setup`, `jigw doctor` | `kur.fish`, `system-check.sh` (+ live security self-test) |
| `jigw lang en\|tr` | new |
| `jigw migrate` | new: v0 project (`.kalip/`, Turkish fields) → v1 |
| `jigw bench` | later |
