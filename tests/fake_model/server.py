"""Start the scripted fake model server for a test (never on the real server's port)."""

from __future__ import annotations

import contextlib
import json
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

SCRIPTED = Path(__file__).with_name("scripted_openai.py")
REAL_SERVER_PORT = 8091


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert port != REAL_SERVER_PORT
    return port


@contextlib.contextmanager
def scripted_server(port: int, steps: list, workdir: Path) -> Iterator[Path]:
    """Serve `steps` (see scripted_openai.py) on `port`; yields the request log path."""
    steps_file = workdir / f"steps-{port}.json"
    steps_file.write_text(json.dumps(steps))
    log = workdir / f"model-log-{port}.jsonl"
    log.touch()
    server = subprocess.Popen(
        [
            sys.executable,
            str(SCRIPTED),
            "--port",
            str(port),
            "--log",
            str(log),
            "--steps",
            str(steps_file),
        ]
    )
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("fake model server did not start")
        yield log
    finally:
        server.terminate()
        server.wait()


def requests(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines()]
