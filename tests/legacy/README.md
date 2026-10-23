# Legacy tests

Tests for the working v0 system in `legacy/qwen-kalip/`. They run the **real Qwen Code CLI**
against **fake model servers**, so they are fast (about a minute), need no GPU, and give the
same result every time.

| Script | What it proves |
|---|---|
| `security_probes.sh` | Every escape route found so far is blocked: shell/monitor/agent tools, writes outside the project, `.git/config` fsmonitor, git hooks, protected files, background memory calls; and the bubblewrap check box hides `$HOME` and `/run`, has no network, keeps `.git` read-only. `PROBE_UNSAFE=1` removes the protections: the Qwen-side probes must then FAIL (proves the probes work). |
| `orchestrator_e2e.sh` | The task loop: fix attempts with check output, auto-fix, NEEDS stop + resume, plain-text report fallback, failure → patch + reset, failed task blocks later tasks, `atla` (skip). |
| `run_all.sh` | Both. |

Fake servers:
- `scripted_openai.py`: replays a fixed list of tool calls (`--steps file.json`) and logs every request.
- `task_model.py`: scripted per task/attempt for the orchestrator scenario.

Safety of the tests themselves: each run uses a temporary `HOME` (real `~/.qwen`, `~/.config/fish`,
`~/.cache` are never touched) and a free port (never the real model server on 8091).

Run after every Qwen Code update:

```bash
bash tests/legacy/run_all.sh
```

Requirements: `fish`, `qwen`, `bwrap`, `git`, `python3`, `curl`; internet once for the
orchestrator test (it pip-installs pytest and ruff into a throw-away venv).
