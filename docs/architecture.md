# Target architecture

Principle: **the core knows no model, agent, OS or sandbox.** Those are adapters. Adding Claude
Code, Ollama, macOS or a Django template means adding an adapter or a template folder, not
changing the loop.

## Repository layout
```
jigwork/
├── README.md, README.tr.md, AGENTS.md, CLAUDE.md, SECURITY.md, CHANGELOG.md, LICENSE
├── pyproject.toml               # package "jigwork"; console scripts: jigwork, jigw
├── src/jigwork/
│   ├── cli.py                   # argument parsing only; calls into the modules below
│   ├── core/                    # model- and platform-independent
│   │   ├── tasks.py             # TASKS.md parse/write (English fields + Turkish aliases), lint
│   │   ├── loop.py              # attempt → auto-fix → checks → fix prompt → commit / patch+reset
│   │   ├── prompts.py           # task prompt, fix prompt, "how to work" rules (English)
│   │   ├── report.py            # report schema, none-normalisation, plain-text fallback
│   │   ├── git_guard.py         # .git/config+hooks hash, protected paths, restore
│   │   ├── project.py           # .jigwork/ dir, config.toml loading with defaults
│   │   └── status.py            # STATUS.md rows, run summaries
│   ├── agents/
│   │   ├── base.py              # Agent protocol (below)
│   │   └── qwen_code/           # settings writer/merger, required-security list, stream reader
│   ├── servers/
│   │   ├── base.py              # health(), start(), stop(), logs()
│   │   ├── llama_cpp.py         # flags from profile, --fit detection, build
│   │   └── external.py          # bring-your-own URL (Ollama, LM Studio, remote)
│   ├── sandbox/
│   │   ├── base.py              # run(cmd, project, readonly_paths, env) -> result
│   │   ├── bwrap.py             # Linux (current kutu_komutu)
│   │   ├── seatbelt.py          # macOS (later)
│   │   └── container.py         # Docker/Podman (later; also the native-Windows path)
│   ├── platform/                # service managers: systemd (Linux), launchd (macOS); WSL detection
│   ├── doctor/                  # hardware report, versions, live security self-test (fake model)
│   └── i18n/                    # en.toml, tr.toml message catalogs; lang selection
├── profiles/<model>/<hardware>.toml     # server flags, context, sampling, threads
├── templates/                   # project templates: _base/, python/, c-cpp/, generic/
│   └── <type>/                  #   files + .jigwork/config.toml + skills/
├── examples/                    # todo/ (also a bench task set), desktop-launcher/
├── shell/                       # fish/, bash/, zsh/: completions and tiny wrappers only
├── install/                     # install.sh (Linux/macOS), install.ps1 (checks/sets up WSL2)
├── tests/
│   ├── unit/
│   ├── fake_model/              # ported from tests/legacy (scripted server + scenario files)
│   ├── integration/             # loop end-to-end with the real agent CLI + fake model
│   ├── security/                # escape probes + "unsafe mode must fail" self-tests
│   └── legacy/                  # current scripts, kept until parity
├── bench/                       # real-model task sets + results (manual, opt-in)
├── docs/                        # design docs (en); docs/en, docs/tr for user docs
└── legacy/                      # v0 reference implementation (frozen)
```

## Interfaces (sketch)
```python
class Agent(Protocol):
    name: str
    def install_settings(self, profile: Profile) -> None: ...      # write/merge user settings, backup first
    def required_security(self) -> list[SecurityCheck]: ...        # what doctor must verify
    def run_task(self, project: Path, prompt: str, schema: Path,
                 limits: Limits, on_event: Callable[[Event], None]) -> AgentResult: ...
    def chat(self, project: Path) -> int: ...                       # interactive session

class ModelServer(Protocol):
    def health(self) -> bool: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...

class Sandbox(Protocol):
    def run(self, project: Path, command: str, readonly: list[Path],
            extra_ro_mounts: list[Path], timeout: int) -> CheckResult: ...
```

## Project directory (v1)
```
<project>/
├── AGENTS.md, CLAUDE.md, GEMINI.md
├── docs/ARCHITECTURE.md, docs/TASKS.md, docs/STATUS.md
├── .qwen/ (agent-specific: settings, skills)       # written by the agent adapter
└── .jigwork/
    ├── config.toml      # [prepare] [autofix] [checks] [skills] [limits]  (English keys)
    └── work/            # logs, patches, resume state (gitignored)
```

## User settings and language
Per-user settings live in `$XDG_CONFIG_HOME/jigwork/config.toml` (default `~/.config/jigwork/`),
handled by `user_config.py`. CLI language: `JIGWORK_LANG`, then `lang` saved by `jigw lang`, then
the system locale (gettext rules: `LC_ALL` > `LC_MESSAGES` > `LANG`, `LANGUAGE` as a preference
list, ignored under `C`/`POSIX`), then English. Catalogs: `src/jigwork/i18n/<lang>.toml`; tests
require identical keys and placeholders in every catalog. argparse's built-in error texts stay
English; its help chrome (usage, section titles, `-h`) is translated.

## Security invariants (must hold for every adapter)
1. The agent cannot execute commands.
2. The agent cannot write outside the project, nor to `.git/`, agent settings, `.jigwork/`,
   AGENTS-style files, TASKS/STATUS, dependency manifests, `.env*`.
3. `.git/config`, `.git/config.worktree` and `.git/hooks` (recursively, symlinks not followed)
   are snapshotted around every agent run; on a mismatch no git command runs before a restore.
4. Checks run with no network, no view of `$HOME`, `/run`, `/tmp`, with `.git` and control files
   read-only, and with tooling (venv) outside the project and read-only.
5. Anything executed on the host (pip install of declared dependencies, NEEDS commands) is either
   user-controlled input or shown to the user first.
6. `jigw doctor` verifies 1–4 live, and the test suite proves the verification fails on an
   unprotected setup.
