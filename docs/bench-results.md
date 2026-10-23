# Bench results (real model)

## 2026-10-23: examples/todo, legacy v0
Setup: Qwen3.6-35B-A3B UD-Q4_K_M, llama.cpp (settings in `context.md`), RTX 4060 Laptop 8 GB,
i7-12700H, 32 GB DDR4-3200, Qwen Code 0.26.0. Generation speed 20–21 tok/s.
Task set: `legacy/qwen-kalip/ornekler/todo/docs/TASKS.md` (4 tasks, Python, tests required).

| Task | Result | Attempts | Time | Notes |
|---|---|---|---|---|
| T1 model + parsing | done | 3 | 8 min 16 s | attempt 2: missing `import pytest` (real error); attempt 3: import order only (led to the auto-fix step). Run before the auto-fix and `(exists)/(new)` changes; first tool call took 1 min 33 s (cold prefix cache). |
| T2 load/save | done | 2 | 2 min 20 s | attempt 1: wrong expectation in the model's own test; fix changed the test (correctly). |
| T3 list operations | done | 1 | 1 min 59 s | auto-fix applied. |
| T4 CLI (argparse) | done | 1 | 5 min 01 s | 20 tool calls; the model rewrote and re-checked its own files. |

Total: 4/4 tasks, 7 agent sessions, about 17.5 minutes. First tool call per session: about 10 s
once the prefix cache was warm.

Caveat: architecture and task breakdown were written by a human/large model; this set measures
execution, not planning. Harder sets are planned in `roadmap.md` (phase 2).
