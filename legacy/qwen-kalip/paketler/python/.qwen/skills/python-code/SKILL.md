---
name: python-code
description: Conventions for writing or editing Python source files in src/. Use for any task that changes .py files outside tests/.
---
# Python code conventions

- Python 3.11+. Prefer the standard library; never add a dependency yourself.
- Type hints on every public function and method. Use `X | None`, `list[str]`, `dict[str, int]`.
- Small functions with one job. If a function grows past ~40 lines, split it.
- `pathlib.Path` for paths, f-strings for formatting, `dataclasses` for plain data.
- Raise specific exceptions (ValueError, KeyError, or a custom one) with a clear message. Never `except: pass`.
- No `print()` for diagnostics in library code; return values or raise.
- Public functions get a short docstring: what it does, what it returns, what it raises.
- Imports: standard library, third party, local; absolute imports only.
- Keep I/O (files, input(), network) at the edges. Core logic is pure functions that tests can call directly.
- When these rules conflict with the existing style of the file you edit, follow the file.
