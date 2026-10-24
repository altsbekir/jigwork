# Qwen Code notes (verified on 0.26.0)

Verified by running the real CLI against fake OpenAI-compatible servers that log requests.
Re-verify with `tests/legacy/` after every Qwen Code update; these are internals and change
(e.g. `tools.exclude` is already deprecated).

## User settings we write (`~/.qwen/settings.json`)
```jsonc
{
  "env": { "LLAMA_API_KEY": "yerel" },                 // any non-empty value
  "modelProviders": { "openai": [{
    "id": "qwen3.6-35b-a3b", "envKey": "LLAMA_API_KEY",
    "baseUrl": "http://127.0.0.1:8091/v1",
    "generationConfig": {
      "timeout": 900000, "streamIdleTimeoutMs": 600000, "maxRetries": 1,
      "contextWindowSize": 65536,                       // must match llama-server -c
      "samplingParams": { "temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0,
                          "presence_penalty": 0, "max_tokens": 16384 }   // sent verbatim
  }}]},
  "security": { "auth": { "selectedType": "openai" } },
  "model": { "name": "qwen3.6-35b-a3b" },
  "memory": { "enableManagedAutoMemory": false, "enableManagedAutoDream": false,
              "enableAutoSkill": false },
  "skills": { "disabledLevels": ["bundled"] },
  "tools": {
    "executionSandbox": { "backend": "bwrap", "filesystem": "workspace-write", "network": "closed" },
    "disabled": ["run_shell_command", "monitor", "agent", "task_stop"]
  },
  "permissions": { "deny": ["Edit(.git/**)", "Edit(.qwen/**)", "Edit(.kalip/**)", "Edit(.env*)",
    "Edit(AGENTS.md)", "Edit(CLAUDE.md)", "Edit(GEMINI.md)", "Edit(docs/TASKS.md)",
    "Edit(docs/STATUS.md)", "Edit(pyproject.toml)"] }
}
```
- `generationConfig` inside a provider entry is sealed: top-level `model.generationConfig` is ignored.
- `samplingParams` is atomic; put every sampling field there.
- `tools.executionSandbox`: "operator scopes only; workspace settings cannot override it".
  Backends `auto|bwrap|landlock`, filesystem `read-only|workspace-write`, network `open|closed`.
  Model/auth traffic stays on the host (the local server is reachable). Under it: skill commands
  and `grep_search` are unavailable.
- `tools.disabled`: removes tools from the registry (never offered, cannot be discovered).
  `tools.exclude` / `tools.core` are deprecated.
- `permissions.deny` rules: `Edit(<glob>)`, glob relative to the project root; blocks `write_file`
  and `edit`, also in yolo mode. `Edit(AGENTS.md)` does not match `sub/AGENTS.md`. Lists merge as
  a union across scopes (a project can add rules, not remove them).
- Verified by `tests/security/test_qwen_code.py` (0.26.0): a project's `.qwen/settings.json` **is
  loaded** (its `tools.disabled` takes effect), yet it cannot undo the user-level protections:
  `tools.disabled: []`, `tools.core`, `executionSandbox.network: open`, `permissions.allow:
  ["Edit(**)", ...]` and `deny: []` there change nothing. User-level `permissions.allow` rules for
  the same paths do not beat our `deny` rules either.
- A tool-list check alone proves nothing for `monitor`, `agent`, `task_stop`: without our
  settings they are still absent from the declared list (deferred tools), but reachable.
- Older docs show `"tools": {"sandbox": true}` / `QWEN_SANDBOX=podman`: that is the container
  sandbox, a different mechanism; we do not use it.

## Tools seen in 0.26.0
`read_file, write_file, edit, glob, grep_search, list_directory, run_shell_command, monitor,
agent, task_stop, skill, tool_search, tool_call, notebook_edit, structured_output` (the last only
with `--json-schema`). With our settings the model sees exactly:
`read_file, list_directory, glob, write_file, edit` (+ `structured_output`).
- `write_file` on an existing file fails unless the file was read in the same session.
- `monitor` runs a shell command in the background and streams its output: treat as a shell.

## Headless mode
`qwen "<prompt>" [flags]` (positional prompt; `-p` is deprecated). Useful flags:
`--approval-mode plan|default|auto-edit|auto|yolo`, `--output-format text|json|stream-json`,
`--json-schema '<json>' | @file` (adds `structured_output`; the session ends on the first valid
call), `--max-wall-time 45m`, `--max-tool-calls N` (both exit with code 55 when exceeded),
`--max-session-turns N`, `--system-prompt`, `--append-system-prompt`, `--continue`, `--resume`.

`stream-json` lines: `{"type":"system","subtype":"init",...tools...}`,
`{"type":"assistant","message":{"content":[{"type":"thinking"|"text"|"tool_use", ...}]}}`,
`{"type":"user","message":{"content":[{"type":"tool_result",...}]}}`,
`{"type":"result","subtype":"success"|"error_during_execution","result":...,"structured_result":{...}}`.
If the model answers in plain text instead of calling `structured_output`: `error_during_execution`
with "Model produced plain text instead of calling the structured_output tool"; take the last
assistant text and parse it.

## When the model server is unreachable
Against a closed port, a headless run retries for ~70 s (with `maxRetries: 1`), prints the error
as assistant text, and ends with `{"type":"result","subtype":"error_during_execution"}` whose
message is `[API Error: Connection error. (cause: connect ECONNREFUSED 127.0.0.1:<port>)]`.
The adapter reports this as `AgentResult.connection_error`.

## Context files
Loads `AGENTS.md` (and `QWEN.md`) from the project, plus `~/.qwen/output-language.md`.

## Interactive status line
Shows the sandbox: `tools / bwrap → bwrap (full) / workspace-write / command network: closed`.
