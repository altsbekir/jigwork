"""The example task set stays runnable, and stays the task set the benchmark was measured on."""

from jigwork.core import tasks

from .conftest import ROOT

TODO = ROOT / "examples/todo/docs/TASKS.md"
BENCHED = ROOT / "legacy/qwen-kalip/ornekler/todo/docs/TASKS.md"


def test_todo_tasks_lint_clean():
    found, issues = tasks.lint(TODO.read_text())
    assert [t.id for t in found] == ["T1", "T2", "T3", "T4"]
    assert issues == []
    assert all(t.status == "pending" and not t.legacy for t in found)


def test_todo_tasks_are_the_benchmarked_ones():
    def content(path):
        return [(t.id, t.title, t.type, t.files, t.task, t.acceptance) for t in tasks.load(path)]

    assert content(TODO) == content(BENCHED)


def test_todo_architecture_is_the_benchmarked_one():
    benched = ROOT / "legacy/qwen-kalip/ornekler/todo/docs/ARCHITECTURE.md"
    assert (ROOT / "examples/todo/docs/ARCHITECTURE.md").read_text() == benched.read_text()
