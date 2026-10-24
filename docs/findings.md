# Findings

Things we learned by testing, each with what we did about it. Several are not documented
anywhere else. Every security item has a probe in `tests/legacy/security_probes.sh`.

## Security

### 1. Disabling the shell tool is not enough: `monitor` runs commands
With only `run_shell_command` disabled, the real model (asked to run `ls`) first tried a
subagent, then found the `monitor` tool ("watch a command's output") and ran `ls -la` through it.
AGENTS.md said "you have no shell"; the model looked for a workaround anyway.
**Fix:** `tools.disabled = ["run_shell_command", "monitor", "agent", "task_stop"]` in user-level
settings. **Lesson:** restrict small models by removing tools, never by instructions.
Without our settings, deferred tools are also reachable through the `tool_search`/`tool_call`
bridge even when not in the declared tool list; behavioural probes catch this, tool-list
checks alone do not.

### 2. Writing inside the project can still escape through git
The agent may write anywhere in the project, `.git/` included. A line in `.git/config` such as
`core.fsmonitor = "<command>"` runs `<command>` on the host, outside every sandbox, the next
time the user runs `git status`. Proven in a test. `.git/hooks/*` is the same.
**Fix:** `permissions.deny: ["Edit(.git/**)", ...]` (blocks `write_file` and `edit`, also in yolo
mode) + a hash of `.git/config` and hooks before/after every agent run (orchestrator aborts;
`qwen-guvenli` offers to restore).

### 3. Other control files
`.qwen/` (project settings could re-enable tools next session), `.kalip/` (checks config),
`AGENTS.md`/`CLAUDE.md`/`GEMINI.md`, `docs/TASKS.md`, `docs/STATUS.md` (the model could mark its
own task done), `pyproject.toml` (dependencies are pip-installed **outside** the box), `.env*`.
**Fix:** all in `permissions.deny`; the check box also mounts them read-only.

### 4. Without the execution sandbox, auto-edit mode writes outside the project
Shell off + `--approval-mode auto-edit` still let `write_file` write to `~/anything`.
**Fix:** `tools.executionSandbox = {backend: bwrap, filesystem: workspace-write, network: closed}`
(user level; workspace settings cannot override it). Outside writes then fail with EROFS.

### 5. The code the model writes is the remaining risk
Running tests = running model-written code. **Fix:** checks run in a bubblewrap box:
`--ro-bind / /`, tmpfs over `/tmp /run /mnt /media $HOME`, project bind-mounted read-write,
`.git` and control files read-only, test venv read-only, `--unshare-all` (no network, own PID
namespace), `--clearenv`. `/run` must be hidden: the D-Bus session socket there could ask
systemd to start processes outside the box. The venv lives outside the project: inside it, the
agent could plant a `.pth` file that runs whenever the orchestrator runs pip on the host.
Remaining, by design: the user eventually runs the project's code; docs must say so.
Two more rules from porting the box (`tests/security/test_bwrap_box.py`): writes to the host are
stopped by two layers (read-only root, tmpfs over HOME), so a probe must remove both to prove
anything; and a protected path that is a symlink is never mounted, because `--ro-bind` follows
it (a check could leave `.env.x -> ~/.ssh/key` for the next check to read).

### 6. Commands the model asks for run outside every sandbox
The NEEDS mechanism shows commands to the user; the user runs them as themselves. Docs and
CLI output must say "read before running"; typosquatted package names are the classic risk.

### 7. Web access stays off
Prompt injection from a fetched page into a small model with write access; also 5–15k tokens
per page. If ever added: page fetch only, with per-call approval.

## Behaviour and performance

### 8. Background memory extraction doubles the work
Qwen Code 0.26 by default sends a second model request after each turn ("managed memory
extraction subagent") and loads the notes into later sessions. On a 20 tok/s local model that
doubles time, and a small model's notes become sticky errors.
**Fix:** `memory.enableManagedAutoMemory = false`, `enableManagedAutoDream = false`,
`enableAutoSkill = false`.

### 9. Bundled skills cost half the system prompt
`skills.disabledLevels = ["bundled"]` cut the system prompt from ~35k to ~18k characters.

### 10. Skills do not work under the execution sandbox
"Skill commands are not yet supported with tools.executionSandbox"; `grep_search` also
disappears. **Fix:** the orchestrator inlines the relevant SKILL.md bodies into the prompt,
chosen by task type (`[skills]` in the project config). More reliable for a small model anyway.

### 11. Prompt-prefix cache makes many short sessions viable
First tool call of a fresh session went from 1 min 33 s to ~10 s once llama-server reused the
identical Qwen Code system prompt across sessions (`--cache-ram 2048`, `-np 1`).

### 12. Mechanical lint errors waste attempts
One real attempt (3.5 min) was spent only on import order. **Fix:** an auto-fix step
(`ruff format`, `ruff check --fix`) in the box before the checks.

### 13. The model returns `["none"]` for "nothing"
In `doubts` and potentially `needs`. A `needs: ["none"]` would stop the run and ask the user to
run "none". **Fix:** normalise none/yok/-/n/a/[] variants to empty.

### 14. The model tries to read files that do not exist yet
**Fix:** files in the prompt are marked `(exists)` or `(new, create it)`.

### 15. Fixing the test instead of the code
Seen once (T2): the test was genuinely wrong and the fix was right, but this is where small
models cheat. **Planned:** warn and mark for human review when a fix attempt changes only test files.

### 16. Context
Qwen3.6 is hybrid (10 attention layers, 40 Gated DeltaNet layers), so the KV cache is small:
64K context is cheap. The agent's own system prompt + tools are ~5–6k tokens; fresh sessions
per task keep context usage low (~20% after a few interactive turns).
