# Tasks: todo

<!--
Görev kuralları:
- Her görev tek, küçük, tek başına test edilebilir bir iş (ideal: 1-3 dosya).
- "dosyalar": modelin okuyacağı/değiştireceği dosyalar.
- "kabul": test edilebilir, ölçülebilir maddeler.
- "tip": kod | test | dokuman
- "durum": bekliyor | tamam | basarisiz  (orkestra günceller; yeni görevi "bekliyor" yaz)
-->

## T1: Todo model and line parsing
durum: bekliyor
tip: kod
dosyalar: src/todo/__init__.py, src/todo/model.py, tests/test_model.py
gorev: Create the todo package. In model.py write a frozen dataclass Todo(title: str, done: bool = False)
and two functions: parse_line(text: str) -> Todo and format_line(todo: Todo) -> str.
kabul:
- "[ ] buy milk" parses to Todo("buy milk", done=False)
- "[x] buy milk" parses to Todo("buy milk", done=True)
- leading and trailing whitespace around the line and the title is ignored
- a line in any other format, or with an empty title, raises ValueError
- format_line(parse_line(s)) == s for "[ ] a" and "[x] a"
- src/todo/__init__.py exists and is empty
- tests in tests/test_model.py cover every point above

## T2: Load and save the todo file
durum: bekliyor
tip: kod
dosyalar: src/todo/storage.py, tests/test_storage.py
gorev: Write load(path: Path) -> list[Todo] and save(path: Path, todos: list[Todo]) -> None
using parse_line and format_line from todo.model.
kabul:
- load returns an empty list when the file does not exist
- load skips empty and whitespace-only lines
- load raises ValueError that includes the line number when a line cannot be parsed
- save writes one line per todo, each ending with a newline, UTF-8 encoded
- save then load returns an equal list (round trip)
- tests use pytest's tmp_path and never touch real files

## T3: Operations on the list
durum: bekliyor
tip: kod
dosyalar: src/todo/ops.py, tests/test_ops.py
gorev: Write add(todos, title) -> list[Todo], complete(todos, position) -> list[Todo]
and remove(todos, position) -> list[Todo]. Positions are 1-based.
kabul:
- every function returns a new list and leaves the input list unchanged
- add appends an open todo; a title that is empty after strip raises ValueError
- complete marks the todo at that position as done; completing a done todo keeps it done
- remove deletes the todo at that position
- a position below 1 or above len(todos) raises ValueError in complete and remove
- tests cover every point above, including the input list staying unchanged

## T4: Command-line interface
durum: bekliyor
tip: kod
dosyalar: src/todo/cli.py, tests/test_cli.py
gorev: Write main(argv: list[str] | None = None, path: Path | None = None) -> int with argparse
subcommands: add TITLE, list, done N, rm N. It loads the file, applies the operation, saves when
something changed, and prints the result. path defaults to Path("todo.txt").
kabul:
- "add buy milk" (title given as separate words) adds "buy milk" and prints "Added: buy milk"
- "list" prints every todo as "N. [ ] title" or "N. [x] title"; with no todos it prints "No todos."
- "done 1" and "rm 1" change the file and print what they did
- a ValueError (bad position, bad file) prints "Error: <message>" to stderr and returns 1
- success returns 0
- tests call main([...], path=tmp_path / "todo.txt") and check output with capsys
