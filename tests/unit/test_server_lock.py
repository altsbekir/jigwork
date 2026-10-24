import json
import os
import subprocess
import sys

from jigwork.servers import lock


def test_using_server_registers_this_process(isolated_home):
    assert not lock.in_use()
    with lock.using_server():
        assert lock.active_users() == [os.getpid()]
    assert not lock.in_use()
    assert lock.users_dir() == isolated_home / ".cache/jigwork/server-users"


def test_dead_and_broken_entries_are_ignored_and_removed(isolated_home):
    folder = lock.users_dir()
    folder.mkdir(parents=True)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (folder / str(dead.pid)).write_text(json.dumps({"pid": dead.pid, "start": "1"}))
    (folder / "garbage").write_text("not json")
    assert lock.active_users() == []
    assert list(folder.iterdir()) == []


def test_reused_pid_does_not_count(isolated_home):
    folder = lock.users_dir()
    folder.mkdir(parents=True)
    # this process is alive, but with another start time it is a different process
    (folder / str(os.getpid())).write_text(json.dumps({"pid": os.getpid(), "start": "-1"}))
    assert lock.active_users() == []


def test_another_process_counts_while_alive(isolated_home):
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        folder = lock.users_dir()
        folder.mkdir(parents=True)
        entry = {"pid": other.pid, "start": lock._start_time(other.pid)}
        (folder / str(other.pid)).write_text(json.dumps(entry))
        assert lock.active_users() == [other.pid]
    finally:
        other.kill()
        other.wait()
    assert lock.active_users() == []
