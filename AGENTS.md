# jigwork: instructions for coding agents working on this repo

jigwork makes a small local LLM (first target: Qwen3.6-35B-A3B on an 8 GB GPU through
Qwen Code) do reliable software work. The model is the tool; jigwork is the jig around it:
small tasks, a locked-down agent, checks in a sandbox, a fix loop, and git as the safety net.

**Status: pre-alpha, private.** A working v0 exists in `legacy/qwen-kalip/` (fish + one Python
script, Turkish names). The job now is to rebuild it as a clean, cross-platform Python package
following `docs/architecture.md` and `docs/roadmap.md`, without losing any behaviour or any
security property of v0.

## Read before changing anything
1. `docs/context.md`: how we got here, the user's setup, what is proven to work.
2. `docs/findings.md`: security and behaviour discoveries. Every one became a protection;
   none of them may be lost.
3. `docs/qwen-code-notes.md`: verified facts about Qwen Code 0.26 (settings keys, tool names,
   output formats). Do not guess Qwen Code behaviour; test it (see tests/legacy for the method).
4. `docs/decisions.md` and `docs/roadmap.md`: what is decided, what is next.

## Non-negotiable rules
- `bash tests/legacy/run_all.sh` must stay green. When a feature moves from legacy to the new
  package, port its tests too, and keep `PROBE_UNSAFE=1` style "tests of the tests" for security.
- Never weaken a protection to make something work. If a protection blocks a feature, stop and
  ask the user.
- Tests never touch the real `$HOME`, real `~/.qwen`, or the real model server (port 8091):
  temporary HOME, free port, fake model. Real-model runs are manual and opt-in (`bench/`).
- Do not modify `legacy/` except to fix a bug the user hits in daily use; it is the reference
  implementation until the new package reaches parity.
- English for code, identifiers, config keys, commit messages, docs in `docs/` and everything
  sent to the model (prompts, AGENTS.md templates, skills). User-facing CLI messages go through
  the i18n catalog (en + tr). Turkish user docs live in `docs/tr/`.
- No personal data in the repo (usernames, home paths, e-mails). Use `~` in docs.

## Working with the user
- Talk to the user in Turkish. They are new to agentic coding but know Python, C/C++, Git and Linux.
  Explain decisions briefly, ask before anything irreversible.
- Their shell is fish (CachyOS / Arch, KDE). Give shell commands in fish syntax.
- They run the real model locally; ask them to run real-model checks and paste output.

## Commands (until the new package exists)
- Tests: `bash tests/legacy/run_all.sh` (needs fish, qwen, bwrap, git, python3, curl).
- Legacy kit install (into the real HOME, only when the user asks): `fish legacy/qwen-kalip/kur.fish`.
