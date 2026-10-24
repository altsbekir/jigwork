"""Which jigwork processes are using the model server right now.

Each `jigw run` / `jigw chat` holds an entry `server-users/<pid>` (with the process start time,
so a reused pid does not count) for as long as it runs; dead entries are ignored and removed.
It answers one question: may jigwork stop a server it started, or does another run still
need it? Nothing outside jigwork reads it.
"""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Iterator
from pathlib import Path

from jigwork.core.checks import cache_dir


def users_dir() -> Path:
    return cache_dir() / "server-users"


def _start_time(pid: int) -> str | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return stat.rsplit(")", 1)[1].split()[19]  # field 22: starttime, after "pid (comm)"


def _alive(pid: int, start: str | None) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass  # exists, owned by someone else
    return start is None or _start_time(pid) in (None, start)


def active_users() -> list[int]:
    """Pids of the jigwork processes using the server; stale entries are deleted."""
    users = []
    folder = users_dir()
    if not folder.is_dir():
        return users
    for entry in folder.iterdir():
        try:
            data = json.loads(entry.read_text())
            pid, start = int(data["pid"]), data.get("start")
        except (OSError, ValueError, KeyError, TypeError):
            entry.unlink(missing_ok=True)
            continue
        if _alive(pid, start):
            users.append(pid)
        else:
            entry.unlink(missing_ok=True)
    return sorted(users)


def in_use() -> bool:
    return bool(active_users())


@contextlib.contextmanager
def using_server() -> Iterator[None]:
    pid = os.getpid()
    folder = users_dir()
    folder.mkdir(parents=True, exist_ok=True)
    entry = folder / str(pid)
    entry.write_text(json.dumps({"pid": pid, "start": _start_time(pid)}))
    try:
        yield
    finally:
        entry.unlink(missing_ok=True)
