# Architecture: todo

## Goal
A tiny command-line todo list for a single user. Todos are kept in a plain text file,
one per line, so the file is easy to read and edit by hand.

## Folder layout
```
src/todo/__init__.py   package marker (empty)
src/todo/model.py      Todo data class + converting one line of text to/from a Todo
src/todo/storage.py    reading and writing the todo file
src/todo/ops.py        pure functions that change a list of todos
src/todo/cli.py        command-line interface (argparse), the only module that prints
tests/test_<module>.py one pytest file per module
docs/                  project docs (this file, tasks, status)
```

## File format
One todo per line: `[ ] buy milk` (open) or `[x] buy milk` (done).
Empty lines are ignored. The file is UTF-8.

## Components
- model.py: `Todo(title: str, done: bool = False)` frozen dataclass; `parse_line`, `format_line`.
- storage.py: `load(path) -> list[Todo]`, `save(path, todos)`. A missing file means an empty list.
- ops.py: `add`, `complete`, `remove`. They return a NEW list and never modify the input.
  Positions are 1-based, as the user sees them.
- cli.py: `main(argv: list[str] | None = None, path: Path | None = None) -> int`.
  Default file: `todo.txt` in the current directory.

## Decisions
- Standard library only. No dependencies.
- Pure functions in model/ops/storage; only cli.py does printing and reads argv.
- Errors are ValueError with a clear message; cli.py turns them into a message and exit code 1.

## Out of scope
- Due dates, priorities, multiple lists, colors.
