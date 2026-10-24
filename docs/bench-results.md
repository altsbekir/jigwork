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

## 2026-10-24: examples/todo, jigwork 0.0.1 (phase 1 parity run)
Setup: as above; `jigw init python`, then `examples/todo` copied in. jigwork started the server
itself and stopped it at the end. Prompts and skills are identical to v0 (parity tests).

| Task | Result | Attempts | Time | Notes |
|---|---|---|---|---|
| T1 model + parsing | done | 3 | 21 min 02 s | the model's own test expected an `Empty` error for `"[ ] "`, which the task's own whitespace rule makes equal to `"[ ]"`; two attempts went into fitting the code to that test. Contains a 12,490-token reply (~14 min of looping thought over the regex). |
| T2 load/save | done | 1 | 3 min 23 s | |
| T3 list operations | done | 1 | 4 min 59 s | |
| T4 CLI (argparse) | done | 3 | ~52 min | attempt 1: tests read `capsys` output collected over several `main()` calls; attempt 2 removed the `Added: ...` prints the acceptance asks for (flagged in its doubts); attempt 3 (~30 min, 27k output tokens) fixed the tests, then asked the user to run `pytest` and `ruff` (NEEDS). The run stopped and stopped the server; `jigw resume` ran the checks, which passed. STATUS shows `0s` because resume times only its own part. |

Total: 4/4 tasks, 8 agent sessions, 81.5 minutes. Server log: 63,180 generated tokens in 73 min
(median 15.6 tok/s, range 10.5–18.8, against 20–21 before; cause not measured), 95,272 prompt
tokens in 7 min; checks took seconds. 6 of 8 sessions ended with a plain-text report instead of
the `structured_output` tool; the fallback parser read all of them.

Changes made after this run:
- A NEEDS list that only runs the project's own check tools (here `pytest`, `ruff`) no longer
  stops the run; the checks run instead (`core/checks.py: only_checks`).
- A run that stops for NEEDS leaves a server jigwork started running for `jigw resume`.
- `jigw resume` opens the server only when the agent has to run again (here the checks passed
  and the model was loaded for nothing).

Open for phase 2: tests that over-specify (exact messages the task does not ask for), very
long thinking replies (no budget yet), repeated runs of one set to separate luck from change
(sampling temperature 0.6), resumed tasks timed only from the resume.
