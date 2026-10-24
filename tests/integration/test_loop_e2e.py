"""The task loop end to end (port of tests/legacy/orchestrator_e2e.sh).

Real `qwen` CLI with the settings jigwork writes, the real bubblewrap check box, a real test
venv (pytest + ruff from the internet, once), and a scripted fake model (task_model.py).

Scenario (todo example, 4 tasks + 1 added later):
  T1  first attempt has a bug, the fix attempt repairs it          -> done after 2 attempts
      also tries to write .git/hooks and AGENTS.md                -> both refused
  T2  unsorted imports (auto-fix), report says needs ["none"]      -> done in 1 attempt
      its test tries to escape the check box                      -> no home, no network, .git ro
  T3  asks the user to run a command (NEEDS)                       -> stops with exit code 2
      `resume` runs the checks and continues                      -> done
  T4  plain-text report, never compiles                           -> failed after 3, patch, reset
  T5  added after T4 failed                                        -> refused until T4 is skipped
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from jigwork.agents.qwen_code import settings
from jigwork.agents.qwen_code.settings import Endpoint
from jigwork.commands import init as commands_init
from jigwork.commands import run as commands_run
from jigwork.core import tasks

from ..fake_model.server import free_port

TASK_MODEL = Path(__file__).parents[1] / "fake_model" / "task_model.py"
TODO_TASKS = Path(__file__).parents[1] / "unit" / "data" / "todo_v0_TASKS.md"

if os.environ.get("JIGWORK_NO_QWEN"):
    pytest.skip("JIGWORK_NO_QWEN is set", allow_module_level=True)
for tool in ("qwen", "bwrap", "git"):
    if shutil.which(tool) is None:
        pytest.fail(f"{tool} is not installed (set JIGWORK_NO_QWEN=1 to skip)", pytrace=False)


def english_tasks() -> str:
    text = TODO_TASKS.read_text(encoding="utf-8")
    for v0, v1 in (
        ("durum: bekliyor", "status: pending"),
        ("tip: kod", "type: code"),
        ("dosyalar:", "files:"),
        ("gorev:", "task:"),
        ("kabul:", "acceptance:"),
    ):
        text = text.replace(v0, v1)
    return text


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def todo(isolated_home, monkeypatch):
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "jigwork test")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "test@example.invalid")
    (isolated_home / "secret").mkdir()
    (isolated_home / "secret/key").write_text("secret")
    port = free_port()
    settings.install(settings.settings_path(), Endpoint(base_url=f"http://127.0.0.1:{port}/v1"))

    # the project comes from `jigw init --type python`: its template is what gets tested
    root = isolated_home / "Projects/todo"
    assert commands_init.run(str(root), "python") == 0
    (root / "docs/TASKS.md").write_text(english_tasks())
    git(root, "commit", "-qam", "todo tasks")

    log = isolated_home / "model.log"
    env = {**os.environ, "PROJ": str(root), "PORT": str(port), "ESCAPE_HOME": str(isolated_home)}
    server = subprocess.Popen([sys.executable, str(TASK_MODEL), str(log)], env=env)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        yield root, log
    finally:
        server.terminate()
        server.wait()


def test_task_loop_end_to_end(todo, capsys, isolated_home):
    root, model_log = todo

    def jigw(command: str) -> tuple[int, str]:
        code = commands_run.run(command, cwd=root)
        captured = capsys.readouterr()
        return code, captured.out + captured.err

    # 1. run: T1 (fix loop), T2 (auto-fix), T3 stops on NEEDS
    code, out = jigw("run")
    assert code == 2, out
    assert "T1 done (attempt 2," in out
    assert "T2 done (attempt 1," in out
    assert "auto-fix applied" in out
    assert "pip install rich" in out
    assert (
        out.count("the agent asks you to run these commands") == 1
    )  # needs ["none"] did not stop T2
    assert (root / "AGENTS.md").read_text().startswith("# Project: todo")
    assert not [h for h in (root / ".git/hooks").iterdir() if not h.name.endswith(".sample")]
    escape = (root / "escape_report.txt").read_text()
    assert set(escape.split(",")) == {"secret-hidden", "net-closed", "git-protected"}
    assert not (isolated_home / "ESCAPED.txt").exists()
    requests = [json.loads(line) for line in model_log.read_text().splitlines()]
    assert any(
        "Fix attempt 2 for task T1" in r["prompt"] and "test_parse_done" in r["prompt"]
        for r in requests
    )
    assert any("src/todo/storage.py (new, create it)" in r["prompt"] for r in requests)

    # 2. run while a task waits for resume
    code, out = jigw("run")
    assert code == 1 and "jigw resume" in out

    # 3. resume: T3 checks, then T4 fails 3 times
    code, out = jigw("resume")
    assert code == 1, out
    assert "T3 done" in out
    assert "Report: CLI written." in out  # the plain-text report was parsed
    assert "T4 failed" in out
    assert list((root / ".jigwork/work").glob("T4-failed-*.patch"))
    assert git(root, "status", "--porcelain") == ""
    status_rows = [
        r for r in (root / "docs/STATUS.md").read_text().splitlines() if r.startswith("| 20")
    ]
    assert len(status_rows) == 4
    assert [t.status for t in tasks.load(root / "docs/TASKS.md")] == [
        "done",
        "done",
        "done",
        "failed",
    ]

    # 4. a later task does not run while T4 is failed
    with (root / "docs/TASKS.md").open("a") as f:
        f.write(
            "\n## T5: Extra\nstatus: pending\ntype: docs\nfiles: README.md\n"
            "task: Write a README.\nacceptance:\n- README exists\n"
        )
    git(root, "commit", "-qam", "add T5")
    code, out = jigw("run")
    assert code == 1 and "T4 is 'failed'" in out
    tasks.set_status(root / "docs/TASKS.md", "T4", "skip")
    git(root, "commit", "-qam", "skip T4")
    code, out = jigw("status")
    assert code == 0
    assert " · T5   pending  docs  Extra" in out
    assert " ↷ T4   skip     code  Command-line interface" in out
