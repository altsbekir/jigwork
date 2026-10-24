# Roadmap

Rule for every phase: `tests/legacy/run_all.sh` stays green; new code comes with tests;
security changes come with probes and "unsafe must fail" self-tests.

## Phase 1: package with parity (current)
Goal: `jigw` does everything the legacy kit does, on Linux, with English names and i18n.
The user switches their daily use to it; `legacy/` is frozen.

1. ✅ **Scaffold**: `pyproject.toml` (Python ≥ 3.11, stdlib only at runtime if possible; dev: pytest,
   ruff), `src/jigwork/`, console scripts `jigwork` + `jigw`, ruff config, pytest config.
2. ✅ **i18n** first (cheap now, expensive later): message catalog en/tr, `jigw lang`, `LANG` default.
3. ✅ **core/tasks.py** + unit tests: port the parser; English fields with Turkish aliases; `jigw tasks lint`.
4. ✅ **core/report.py, prompts.py, git_guard.py, status.py** + unit tests (port from orkestra.py).
5. ✅ **sandbox/bwrap.py** + port of the box probes (`tests/security/`).
6. ✅ **agents/qwen_code/**: settings merge (backup, union lists), required-security list, stream
   reader, run_task, chat (with the .git guard of `qwen-guvenli`).
7. **core/loop.py**: the attempt loop; port `orchestrator_e2e.sh` to `tests/integration/` (pytest).
8. **servers/llama_cpp.py + platform/systemd.py + profiles/**: `jigw server ...`, the user-lock
   for the desktop launcher, `--fit` detection, `server build`.
9. **templates/** (English, `.jigwork/config.toml`) + `jigw init` + `jigw migrate` for v0 projects
   (the user's `~/Projeler/deneme` is the first migration test).
10. **doctor**: hardware/versions (from system-check.sh) + live security self-test with the fake model.
11. **shell/fish** completions; **docs/en + docs/tr** user guide; `README.tr.md`.
12. **Parity check with the user** on their machine: real-model run of `examples/todo`, compare with
    `docs/bench-results.md`.

## Phase 2: hardening and evidence
- Warn + "human review" mark when a fix attempt changes only test files (findings #15).
- `bench/`: harder task sets (fix a bug in existing code, multi-file change, read-then-extend);
  record pass rate, attempts, time; `jigw bench`.
- Optional "thinking off" for doc-type tasks (sampling per task type).
- CI (GitHub Actions, Linux): unit + integration + security with the fake model. Note: Ubuntu
  runners may restrict unprivileged user namespaces (AppArmor) for bwrap; may need a sysctl step.
- SECURITY.md with the threat model; CHANGELOG; license.

## Phase 3: breadth
- macOS: seatbelt sandbox backend, launchd service, CI job on manual trigger.
- Container isolation mode (agent + checks in Docker/Podman): native Windows path.
- `servers/external.py` presets for Ollama and LM Studio.
- More templates (TypeScript/Node, Django).
- More agents (opencode, Claude Code, Codex CLI): each needs its own way to remove command tools,
  confine writes and protect files, and must pass the same probes.
- Planner integration: a large model writes ARCHITECTURE.md + TASKS.md, the local model executes.

## Going public (after phase 2)
1–2 weeks of real use, bench numbers in README, SECURITY.md, license, English + Turkish docs.
