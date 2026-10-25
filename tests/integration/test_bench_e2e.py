"""jigw bench with the real Qwen Code CLI and bubblewrap against the scripted fake model.

The bench project lives under ~/.cache/jigwork/bench/ (the default --out): this checks that
the agent and the check box work there like in any project. The fake model's todo scenario
(see test_loop_e2e.py): T1 done after a fix, T2 done, T3 stops for NEEDS, T4 not reached.
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

import pytest

from jigwork.agents.qwen_code import QwenCode, settings
from jigwork.agents.qwen_code.settings import Endpoint
from jigwork.commands import bench as commands_bench
from jigwork.core import bench
from jigwork.doctor.fake_model import free_port
from jigwork.sandbox.bwrap import BwrapSandbox

from .test_loop_e2e import TASK_MODEL, english_tasks

ROOT = TASK_MODEL.parents[2]

if os.environ.get("JIGWORK_NO_QWEN"):
    pytest.skip("JIGWORK_NO_QWEN is set", allow_module_level=True)
for tool in ("qwen", "bwrap", "git"):
    if shutil.which(tool) is None:
        pytest.fail(f"{tool} is not installed (set JIGWORK_NO_QWEN=1 to skip)", pytrace=False)


def test_bench_run_on_a_fresh_project(isolated_home, monkeypatch):
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "jigwork test")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "test@example.invalid")
    port = free_port()
    settings.install(settings.settings_path(), Endpoint(base_url=f"http://127.0.0.1:{port}/v1"))
    bench_set = isolated_home / "sets/todo"
    (bench_set / "docs").mkdir(parents=True)
    (bench_set / "bench.toml").write_text('name = "todo"\ntype = "python"\n')
    shutil.copyfile(ROOT / "examples/todo/docs/ARCHITECTURE.md", bench_set / "docs/ARCHITECTURE.md")
    (bench_set / "docs/TASKS.md").write_text(english_tasks())
    out = isolated_home / ".cache/jigwork/bench/todo-test"
    project = out / "run-1/todo"

    log = isolated_home / "model.log"
    env = {**os.environ, "PROJ": str(project), "PORT": str(port), "ESCAPE_HOME": str(isolated_home)}
    server = subprocess.Popen([sys.executable, str(TASK_MODEL), str(log)], env=env)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        code = commands_bench.run_set(
            bench.load_set(bench_set), 1, out, QwenCode(), BwrapSandbox(), None
        )
    finally:
        server.terminate()
        server.wait()

    assert code == 0
    run = json.loads((out / "results.json").read_text())["runs"][0]
    assert run["exit_code"] == 2  # T3 asked for a command
    assert [(t["task"], t["status"], t["attempts"]) for t in run["tasks"]] == [
        ("T1", "done", 2),
        ("T2", "done", 1),
        ("T3", "pending", 1),
        ("T4", "pending", 0),
    ]
    assert run["tasks"][0]["output_tokens"] > 0  # the stats came through the real agent
    assert "| T1 | 1/1 | 2 |" in (out / "summary.md").read_text()
