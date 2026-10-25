"""jigw bench with a scripted agent and a plain sandbox (core/bench.py, commands/bench.py)."""

import json
import subprocess

import pytest

from jigwork import cli
from jigwork.commands import bench as commands_bench
from jigwork.core import bench

from .test_loop import TASKS, PlainSandbox, ScriptedAgent, write

CONFIG = """\
[prepare]
kind = "none"
[checks]
a_is_good = "grep -q good src/a.py"
[limits]
attempts = 2
"""


class BenchAgent(ScriptedAgent):
    def __init__(self, script):
        super().__init__(script)
        self.installed = []

    def install_project(self, project, skills):
        self.installed.append(project)
        return [], []

    def model_name(self):
        return "fake-model"


class NoServer:
    def is_up(self):
        return True

    def wait_back(self):
        return True

    def counters(self):
        return None


@pytest.fixture
def bench_set(tmp_path, monkeypatch):
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "t")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "t@example.invalid")
    root = tmp_path / "sets/two"
    (root / "docs").mkdir(parents=True)
    (root / "bench.toml").write_text('name = "two"\ntype = "generic"\ndescription = "Two tasks"\n')
    (root / "docs/ARCHITECTURE.md").write_text("# Two\n")
    (root / "docs/TASKS.md").write_text(TASKS)
    (root / "seed/.jigwork").mkdir(parents=True)
    (root / "seed/.jigwork/config.toml").write_text(CONFIG)  # seed replaces template files
    (root / "seed/src").mkdir()
    (root / "seed/src/old.py").write_text("existing code\n")
    return root


def test_load_set(bench_set):
    loaded = bench.load_set(bench_set)
    assert (loaded.name, loaded.project_type, loaded.description) == ("two", "generic", "Two tasks")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda r: (r / "bench.toml").unlink(), "bench.toml"),
        (lambda r: (r / "bench.toml").write_text('type = "rust"\n'), "type must be one of"),
        (lambda r: (r / "bench.toml").write_text("type = \n"), "bench.toml"),
        (lambda r: (r / "bench.toml").write_text('type = "generic"\nname = "a b"\n'), "name"),
        (lambda r: (r / "docs/TASKS.md").unlink(), "TASKS.md is missing"),
        (lambda r: (r / "docs/TASKS.md").write_text("## T1: x\n"), "jigw tasks lint"),
    ],
)
def test_bad_sets(bench_set, change, message):
    change(bench_set)
    with pytest.raises(bench.BenchError, match=message):
        bench.load_set(bench_set)


def test_make_project(bench_set, tmp_path):
    agent = BenchAgent({})
    root = bench.make_project(bench.load_set(bench_set), tmp_path / "out", agent.install_project)
    assert root == tmp_path / "out/two" and agent.installed == [root]
    assert (root / "docs/TASKS.md").read_text() == TASKS
    assert (root / "src/old.py").read_text() == "existing code\n"
    assert (root / ".jigwork/config.toml").read_text() == CONFIG
    assert (root / "AGENTS.md").exists()  # from the template
    git = ["git", "-C", str(root)]
    status = subprocess.run([*git, "status", "--porcelain"], capture_output=True, text=True)
    assert status.stdout == ""
    log = subprocess.run([*git, "log", "--format=%s"], capture_output=True, text=True)
    assert log.stdout == "bench set two\n"


def flaky_t1(project, prompt):
    """Good at once in run 1; in run 2 a bug that the fix attempt repairs."""
    first_run = "run-1" in str(project)
    return write("src/a.py", "good\n" if first_run else "bad\n")(project, prompt)


SCRIPT = {
    ("T1", 1): flaky_t1,
    ("T1", 2): write("src/a.py", "good\n"),
    ("T2", 1): write("src/b.py", ""),
}


def test_run_set_repeats_on_fresh_projects(bench_set, tmp_path, capsys):
    out = tmp_path / "results"
    agent = BenchAgent(SCRIPT)
    code = commands_bench.run_set(
        bench.load_set(bench_set), 2, out, agent, PlainSandbox(), NoServer()
    )
    assert code == 0
    assert agent.installed == [out / "run-1/two", out / "run-2/two"]
    data = json.loads((out / "results.json").read_text())
    assert (data["set"], data["model"], data["repeat"]) == ("two", "fake-model", 2)
    assert [r["done"] for r in data["runs"]] == [2, 2]
    assert [[t["attempts"] for t in r["tasks"]] for r in data["runs"]] == [[1, 1], [2, 1]]
    table = (out / "summary.md").read_text()
    assert "| T1 | 2/2 | 1.5 (1–2) |" in table
    assert "| T2 | 2/2 | 1 |" in table
    assert "Tasks done: 4/4; all tasks done in 2/2 runs." in table
    shown = capsys.readouterr().out
    assert "Run 2: 2/2 tasks done" in shown and table in shown


def test_a_failed_task_and_the_one_after_it(bench_set, tmp_path):
    out = tmp_path / "results"
    script = {("T1", 1): write("src/a.py", "bad\n"), ("T1", 2): write("src/a.py", "bad\n")}
    code = commands_bench.run_set(
        bench.load_set(bench_set), 1, out, BenchAgent(script), PlainSandbox(), NoServer()
    )
    assert code == 0  # the bench completed; the task result is in the table
    run = json.loads((out / "results.json").read_text())["runs"][0]
    assert run["exit_code"] == 1 and run["done"] == 0
    assert [(t["task"], t["status"], t["attempts"]) for t in run["tasks"]] == [
        ("T1", "failed", 2),
        ("T2", "pending", 0),  # not reached
    ]
    table = (out / "summary.md").read_text()
    assert "| T1 | 0/1 | - |" in table and "| T2 | 0/1 | - | - |" in table


def test_refuses_a_used_output_folder(bench_set, tmp_path, capsys):
    out = tmp_path / "results"
    out.mkdir()
    (out / "x").write_text("")
    code = commands_bench.run_set(
        bench.load_set(bench_set), 1, out, BenchAgent(SCRIPT), PlainSandbox(), NoServer()
    )
    assert code == 1 and "is not empty" in capsys.readouterr().err


def test_bad_set_and_repeat_are_refused(tmp_path, capsys):
    assert commands_bench.run(str(tmp_path / "nothing")) == 1
    assert "Not a usable bench set" in capsys.readouterr().err


def test_bad_repeat(bench_set, capsys):
    assert commands_bench.run(str(bench_set), repeat=0) == 1
    assert "--repeat must be 1 or more" in capsys.readouterr().err


def test_cli_wiring(monkeypatch):
    seen = []
    monkeypatch.setattr(commands_bench, "run", lambda *args: seen.append(args) or 0)
    assert cli.main(["bench", "sets/x", "--repeat", "3", "--out", "o"]) == 0
    assert cli.main(["bench", "sets/x"]) == 0
    assert seen == [("sets/x", 3, "o"), ("sets/x", 1, None)]


def test_the_todo_example_is_a_bench_set():
    from .conftest import ROOT

    loaded = bench.load_set(ROOT / "examples/todo")
    assert (loaded.name, loaded.project_type) == ("todo", "python")
