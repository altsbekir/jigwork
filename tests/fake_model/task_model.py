"""Fake model for the task-loop end-to-end test (port of tests/legacy/task_model.py).

Reads the task id ("Task T1") and attempt ("Fix attempt 2") from the prompt and replays a
scripted list of tool calls for that (task, attempt): a buggy first attempt that the fix loop
must repair, a file with unsorted imports for the auto-fix step, a NEEDS stop, a plain-text
report instead of structured_output, a task that never passes, a test that tries to escape
the check box, and writes to protected files that must be refused.

Usage: PROJ=<project dir> PORT=<port> ESCAPE_HOME=<home> python3 task_model.py LOG.jsonl
"""

import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

P = os.environ["PROJ"]
HOME = os.environ["ESCAPE_HOME"]
LOG = sys.argv[1]

MODEL_BUGGY = """from dataclasses import dataclass


@dataclass(frozen=True)
class Todo:
    title: str
    done: bool = False


def parse_line(text: str) -> Todo:
    text = text.strip()
    if text.startswith("[ ] "):
        return Todo(text[4:].strip(), False)
    if text.startswith("[x] "):
        return Todo(text[4:].strip(), False)  # BUG: done must be True
    raise ValueError(f"bad line: {text!r}")


def format_line(todo: Todo) -> str:
    return f"[{'x' if todo.done else ' '}] {todo.title}"
"""
MODEL_OK = MODEL_BUGGY.replace(
    "Todo(text[4:].strip(), False)  # BUG: done must be True", "Todo(text[4:].strip(), True)"
)
TEST_MODEL = """import pytest

from todo.model import Todo, format_line, parse_line


def test_parse_open():
    assert parse_line("[ ] buy milk") == Todo("buy milk", False)


def test_parse_done():
    assert parse_line("[x] buy milk") == Todo("buy milk", True)


def test_bad_line():
    with pytest.raises(ValueError):
        parse_line("buy milk")


@pytest.mark.parametrize("s", ["[ ] a", "[x] a"])
def test_round_trip(s):
    assert format_line(parse_line(s)) == s
"""
# unsorted imports: the auto-fix step must sort them without spending an attempt
STORAGE = """from todo.model import Todo, format_line, parse_line
from pathlib import Path


def load(path: Path) -> list[Todo]:
    if not path.exists():
        return []
    todos = []
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            todos.append(parse_line(line))
        except ValueError as e:
            raise ValueError(f"line {no}: {e}") from e
    return todos


def save(path: Path, todos: list[Todo]) -> None:
    path.write_text("".join(format_line(t) + "\\n" for t in todos), encoding="utf-8")
"""
# a test that tries to escape the check box: write to the real home, read a secret there,
# reach the network, plant a git hook
TEST_STORAGE = """import socket
from pathlib import Path

from todo.model import Todo
from todo.storage import load, save


def test_round_trip(tmp_path):
    p = tmp_path / "t.txt"
    save(p, [Todo("a"), Todo("b", True)])
    assert load(p) == [Todo("a"), Todo("b", True)]


def test_missing(tmp_path):
    assert load(tmp_path / "missing.txt") == []


def test_escape_attempt():
    home = Path("__REAL_HOME__")
    result = []
    try:
        (home / "ESCAPED.txt").write_text("out of the box")  # HOME in the box is an empty tmpfs
    except OSError:
        pass
    try:
        (home / "secret" / "key").read_text()
        result.append("secret-read")
    except OSError:
        result.append("secret-hidden")
    try:
        socket.create_connection(("1.1.1.1", 80), timeout=2)
        result.append("net-open")
    except OSError:
        result.append("net-closed")
    try:
        Path(".git/hooks/post-commit").write_text("#!/bin/sh\\necho ESCAPED")
        result.append("git-written")
    except OSError:
        result.append("git-protected")
    Path("escape_report.txt").write_text(",".join(result))
""".replace("__REAL_HOME__", HOME)

OPS = """from todo.model import Todo


def add(todos: list[Todo], title: str) -> list[Todo]:
    if not title.strip():
        raise ValueError("empty title")
    return [*todos, Todo(title.strip())]
"""
OPS_TEST = """import pytest

from todo.model import Todo
from todo.ops import add


def test_add():
    assert add([], "a") == [Todo("a")]


def test_empty():
    with pytest.raises(ValueError):
        add([], " ")
"""
CLI_BROKEN = "def main(:\n    pass\n"


def w(path, content):
    return ("write_file", {"file_path": f"{P}/{path}", "content": content})


def r(path):
    return ("read_file", {"file_path": f"{P}/{path}"})


def report(changed, done, needs=(), doubts="none"):
    return (
        "structured_output",
        {"changed": list(changed), "done": done, "needs": list(needs), "doubts": doubts},
    )


SCENARIO = {
    ("T1", 1): [
        r("AGENTS.md"),
        w("src/todo/__init__.py", ""),
        w("src/todo/model.py", MODEL_BUGGY),
        w("tests/test_model.py", TEST_MODEL),
        w(".git/hooks/pre-commit", "#!/bin/sh\necho evil"),  # a deny rule must refuse this
        w("AGENTS.md", "tampered"),  # and this
        report(
            ["src/todo/__init__.py", "src/todo/model.py", "tests/test_model.py"], "Model written."
        ),
    ],
    ("T1", 2): [
        r("src/todo/model.py"),
        w("src/todo/model.py", MODEL_OK),
        report(["src/todo/model.py"], "Fixed done=True."),
    ],
    ("T2", 1): [
        w("src/todo/storage.py", STORAGE),
        w("tests/test_storage.py", TEST_STORAGE),
        report(
            ["src/todo/storage.py", "tests/test_storage.py"],
            "Storage written.",
            needs=["none"],
            doubts=["none"],
        ),
    ],
    ("T3", 1): [
        w("src/todo/ops.py", OPS),
        w("tests/test_ops.py", OPS_TEST),
        report(
            ["src/todo/ops.py"],
            "ops written",
            needs=["pip install rich"],
            doubts="rich may be needed",
        ),
    ],
    ("T4", 1): [
        w("src/todo/cli.py", CLI_BROKEN),
        "TEXT",
    ],  # plain text instead of structured_output
    ("T4", 2): [w("src/todo/cli.py", CLI_BROKEN), report(["src/todo/cli.py"], "tried")],
    ("T4", 3): [w("src/todo/cli.py", CLI_BROKEN), report(["src/todo/cli.py"], "tried again")],
}


def chunk(delta, finish=None):
    return {
        "id": "x",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "m",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok","data":[{"id":"qwen3.6-35b-a3b"}]}')

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msgs = req["messages"]
        system = next((m["content"] for m in msgs if m["role"] == "system"), "")
        system = system if isinstance(system, str) else json.dumps(system)
        main = system.startswith("You are Qwen Code")
        users = json.dumps(
            [m.get("content") for m in msgs if m["role"] == "user"], ensure_ascii=False
        )
        task = re.search(r"Task (T\d+)", users)
        fix = re.search(r"Fix attempt (\d+)", users)
        key = (task.group(1) if task else "?", int(fix.group(1)) if fix else 1)
        step = sum(1 for m in msgs if m["role"] == "tool")
        steps = SCENARIO.get(key, [])
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(
                json.dumps({"key": key, "step": step, "main": main, "prompt": users[:6000]}) + "\n"
            )
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if not main or step >= len(steps):
            out = [chunk({"role": "assistant", "content": "ok"}), chunk({}, "stop")]
        elif steps[step] == "TEXT":
            text = "CHANGED: src/todo/cli.py\nDONE: CLI written.\nNEEDS: none\nDOUBTS: none"
            out = [chunk({"role": "assistant", "content": text}), chunk({}, "stop")]
        else:
            name, args = steps[step]
            call = {"index": 0, "id": f"c{step}", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)}}  # fmt: skip
            out = [chunk({"role": "assistant", "tool_calls": [call]}), chunk({}, "tool_calls")]
        # OpenAI-style usage chunk, so the run stats have token counts (core/stats.py)
        usage = {"prompt_tokens": 1000 + step, "completion_tokens": 10 + step}
        out.append({**chunk({}), "choices": [], "usage": {**usage, "total_tokens": 1010}})
        for c in out:
            self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")


HTTPServer(("127.0.0.1", int(os.environ["PORT"])), Handler).serve_forever()
