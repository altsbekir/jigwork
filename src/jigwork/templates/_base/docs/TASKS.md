# Tasks: {{PROJECT_NAME}}

<!--
Write tasks BELOW this comment (or have a larger model write them). Rules:
- Each task is one small job that can be tested on its own (ideally 1-3 files).
- "files": the files the model reads or changes.
- "acceptance": testable, measurable points.
- "type": code | test | docs  (decides which skills go into the prompt)
- "status": pending | done | failed | skip  (jigwork updates it; write "pending")
Check the file with: jigw tasks lint

Example:

## T1: Add a function that parses a todo line
status: pending
type: code
files: src/todo/parser.py, tests/test_parser.py
task: Write parse_line(text) that turns "[x] buy milk" into a Todo(done=True, title="buy milk").
acceptance:
- "[ ] a" gives done=False, title="a"
- "[x] a" gives done=True
- any other format raises ValueError
- tests for all three cases exist and pass
-->
