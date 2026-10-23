"""Fake model for the orchestrator end-to-end test.

Reads the task id ("Task T1") and attempt ("Fix attempt 2") from the prompt and replays
a scripted list of tool calls for that (task, attempt): a buggy first attempt that the
fix loop must repair, a file with unsorted imports for the auto-fix step, a NEEDS stop,
a plain-text report instead of structured_output, a task that never passes, a test that
tries to escape the check box, and writes to protected files that must be refused.

Usage: PROJ=<project dir> PORT=<port> python3 task_model.py LOG.jsonl
"""
import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

P = os.environ["PROJ"]
LOG = sys.argv[1]

MODEL_BUGGY = '''from dataclasses import dataclass


@dataclass(frozen=True)
class Todo:
    title: str
    done: bool = False


def parse_line(text: str) -> Todo:
    text = text.strip()
    if text.startswith("[ ] "):
        return Todo(text[4:].strip(), False)
    if text.startswith("[x] "):
        return Todo(text[4:].strip(), False)  # HATA: done True olmalı
    raise ValueError(f"bad line: {text!r}")


def format_line(todo: Todo) -> str:
    return f"[{'x' if todo.done else ' '}] {todo.title}"
'''
MODEL_OK = MODEL_BUGGY.replace("Todo(text[4:].strip(), False)  # HATA: done True olmalı", "Todo(text[4:].strip(), True)")
MODEL_OK = MODEL_OK.replace('    raise ValueError(f"bad line: {text!r}")',
                            '    raise ValueError(f"bad line: {text!r}")').replace(
    'def parse_line(text: str) -> Todo:\n    text = text.strip()',
    'def parse_line(text: str) -> Todo:\n    text = text.strip()\n    if len(text) <= 4 or not text[4:].strip():\n        raise ValueError(f"bad line: {text!r}")')
TEST_MODEL = '''import pytest

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
'''
STORAGE = '''from todo.model import Todo, format_line, parse_line
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
'''
# Kaçış denemesi yapan test: kontrol kutusunda ev klasörüne yazmayı ve internete çıkmayı dener
TEST_STORAGE = '''import socket
from pathlib import Path

from todo.model import Todo
from todo.storage import load, save


def test_round_trip(tmp_path):
    p = tmp_path / "t.txt"
    save(p, [Todo("a"), Todo("b", True)])
    assert load(p) == [Todo("a"), Todo("b", True)]


def test_missing(tmp_path):
    assert load(tmp_path / "yok.txt") == []


def test_kacis_denemesi():
    gercek = Path("__REAL_HOME__")
    sonuc = []
    try:
        (gercek / "KACIS.txt").write_text("kutudan kaçtım")  # kutuda HOME boş bir tmpfs
    except OSError:
        pass
    try:
        (gercek / "gizli" / "anahtar").read_text()
        sonuc.append("sir-okundu")
    except OSError:
        sonuc.append("sir-okunamadi")
    try:
        socket.create_connection(("1.1.1.1", 80), timeout=2)
        sonuc.append("ag-acik")
    except OSError:
        sonuc.append("ag-kapali")
    try:
        Path(".git/hooks/post-commit").write_text("#!/bin/sh\\necho KACIS")
        sonuc.append("git-yazildi")
    except OSError:
        sonuc.append("git-korundu")
    Path("kacis_raporu.txt").write_text(",".join(sonuc))
'''
TEST_STORAGE = TEST_STORAGE.replace("__REAL_HOME__", os.environ["HOME"])

OPS = '''from todo.model import Todo


def add(todos: list[Todo], title: str) -> list[Todo]:
    if not title.strip():
        raise ValueError("empty title")
    return [*todos, Todo(title.strip())]
'''
OPS_TEST = '''import pytest

from todo.model import Todo
from todo.ops import add


def test_add():
    assert add([], "a") == [Todo("a")]


def test_empty():
    with pytest.raises(ValueError):
        add([], " ")
'''
CLI_BOZUK = "def main(:\n    pass\n"


def w(path, content):
    return ("write_file", {"file_path": f"{P}/{path}", "content": content})


def r(path):
    return ("read_file", {"file_path": f"{P}/{path}"})


def rapor(changed, done, needs=(), doubts="none"):
    return ("structured_output", {"changed": list(changed), "done": done, "needs": list(needs), "doubts": doubts})


SENARYO = {
    ("T1", 1): [r("AGENTS.md"), w("src/todo/__init__.py", ""), w("src/todo/model.py", MODEL_BUGGY),
                w("tests/test_model.py", TEST_MODEL),
                w(".git/hooks/pre-commit", "#!/bin/sh\necho kotu"),   # deny kuralı engellemeli
                w("AGENTS.md", "bozuldu"),                            # deny kuralı engellemeli
                rapor(["src/todo/__init__.py", "src/todo/model.py", "tests/test_model.py"], "Model yazıldı.")],
    ("T1", 2): [r("src/todo/model.py"), w("src/todo/model.py", MODEL_OK),
                rapor(["src/todo/model.py"], "done=True hatası düzeltildi.")],
    ("T2", 1): [w("src/todo/storage.py", STORAGE), w("tests/test_storage.py", TEST_STORAGE),
                rapor(["src/todo/storage.py", "tests/test_storage.py"], "Storage yazıldı.", needs=["none"], doubts=["none"])],
    ("T3", 1): [w("src/todo/ops.py", OPS), w("tests/test_ops.py", OPS_TEST),
                rapor(["src/todo/ops.py"], "ops yazıldı", needs=["pip install rich"], doubts="rich gerekebilir")],
    ("T4", 1): [w("src/todo/cli.py", CLI_BOZUK), "METIN"],   # structured_output yerine düz metin
    ("T4", 2): [w("src/todo/cli.py", CLI_BOZUK), rapor(["src/todo/cli.py"], "denedim")],
    ("T4", 3): [w("src/todo/cli.py", CLI_BOZUK), rapor(["src/todo/cli.py"], "yine denedim")],
}


def chunk(delta, finish=None):
    return {"id": "x", "object": "chat.completion.chunk", "created": int(time.time()), "model": "m",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok","data":[{"id":"qwen3.6-35b-a3b"}]}')

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msgs = req["messages"]
        sys_txt = next((m["content"] for m in msgs if m["role"] == "system"), "")
        sys_txt = sys_txt if isinstance(sys_txt, str) else json.dumps(sys_txt)
        users = [m for m in msgs if m["role"] == "user"]
        ilk = users[-1]["content"] if len(users) == 1 else users[0]["content"]
        ilk = ilk if isinstance(ilk, str) else json.dumps(ilk, ensure_ascii=False)
        tum = json.dumps([m.get("content") for m in msgs if m["role"] == "user"], ensure_ascii=False)
        g = re.search(r"Task (T\d+)", tum)
        f = re.search(r"Fix attempt (\d+)", tum)
        anahtar = (g.group(1) if g else "?", int(f.group(1)) if f else 1)
        adim = sum(1 for m in msgs if m["role"] == "tool")
        adimlar = SENARYO.get(anahtar, [])
        with open(LOG, "a") as lf:
            lf.write(json.dumps({"anahtar": anahtar, "adim": adim, "ana": sys_txt.startswith("You are Qwen Code"),
                                 "prompt": tum[:6000], "son_tool": next((str(m.get("content"))[:200] for m in reversed(msgs) if m["role"] == "tool"), None)},
                                ensure_ascii=False) + "\n")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if not sys_txt.startswith("You are Qwen Code") or adim >= len(adimlar):
            out = [chunk({"role": "assistant", "content": "tamam"}), chunk({}, "stop")]
        elif adimlar[adim] == "METIN":
            metin = "CHANGED: src/todo/cli.py\nDONE: CLI yazıldı.\nNEEDS: none\nDOUBTS: none"
            out = [chunk({"role": "assistant", "content": metin}), chunk({}, "stop")]
        else:
            ad, args = adimlar[adim]
            out = [chunk({"role": "assistant", "tool_calls": [{"index": 0, "id": f"c{adim}", "type": "function",
                                                               "function": {"name": ad, "arguments": json.dumps(args)}}]}),
                   chunk({}, "tool_calls")]
        for c in out:
            self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")


HTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
