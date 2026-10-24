import importlib.util
import sys
from pathlib import Path

import pytest

from jigwork import i18n
from jigwork.cli import main
from jigwork.core import tasks
from jigwork.core.tasks import Task, lint, parse, set_status

DATA = Path(__file__).parent / "data"
ROOT = Path(__file__).parents[2]
LEGACY = ROOT / "legacy" / "qwen-kalip" / "orkestra" / "orkestra.py"

ENGLISH = """\
# Tasks: demo

<!--
Example, ignored:
## T9: Not a task
status: pending
-->

## T1: Parse lines
status: pending
type: code
files: src/a.py, tests/test_a.py
task: Write parse_line(text).
It returns a Todo.
acceptance:
- "[ ] a" gives done=False
- "[x] a" gives done=True

## T2 - Docs
status: done
type: docs
files:
- README.md
task: Write a README.
acceptance: README exists
"""


# --- parsing ---------------------------------------------------------------------------------


def test_parse_english():
    t1, t2 = parse(ENGLISH)
    assert t1 == Task(
        id="T1",
        title="Parse lines",
        line=9,
        status="pending",
        status_line=10,
        type="code",
        files=["src/a.py", "tests/test_a.py"],
        task="Write parse_line(text).\nIt returns a Todo.",
        acceptance=['"[ ] a" gives done=False', '"[x] a" gives done=True'],
        legacy=False,
    )
    assert (t2.id, t2.title, t2.status, t2.type) == ("T2", "Docs", "done", "docs")
    assert t2.files == ["README.md"]
    assert t2.acceptance == ["README exists"]


def test_parse_legacy_turkish_example():
    parsed = tasks.load(DATA / "todo_v0_TASKS.md")
    assert [t.id for t in parsed] == ["T1", "T2", "T3", "T4"]
    assert all(t.legacy and t.status == "pending" and t.type == "code" for t in parsed)
    assert parsed[0].files == ["src/todo/__init__.py", "src/todo/model.py", "tests/test_model.py"]
    assert len(parsed[0].acceptance) == 7
    assert parsed[0].task.startswith("Create the todo package.")
    assert parsed[0].task.endswith("format_line(todo: Todo) -> str.")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("bekliyor", "pending"),
        ("Tamam", "done"),
        ("başarısız", "failed"),
        ("basarisiz", "failed"),
        ("atla", "skip"),
        ("atlandı", "skip"),
        ("DONE", "done"),
        ("later", "later"),
    ],
)
def test_status_aliases(raw, expected):
    (task,) = parse(f"## T1: x\nstatus: {raw}\n")
    assert task.status == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("kod", "code"), ("dokuman", "docs"), ("Dokümantasyon", "docs"), ("test", "test"), ("x", "x")],
)
def test_type_aliases(raw, expected):
    (task,) = parse(f"## T1: x\ntype: {raw}\n")
    assert task.type == expected


def test_defaults_when_fields_missing():
    (task,) = parse("## t3: Lower-case id\n")
    assert (task.id, task.status, task.status_line, task.type) == ("T3", "pending", None, "code")


def test_fields_are_case_insensitive_and_may_be_indented():
    (task,) = parse("## T1: x\n  Status: done\n  TASK: do it\n")
    assert (task.status, task.task) == ("done", "do it")


def test_other_heading_ends_task():
    (task,) = parse("## T1: x\ntask: do it\n\n## Notes\nnot part of T1\n")
    assert task.task == "do it"


def test_text_before_first_task_is_ignored():
    assert parse("# Tasks\nstatus: done\ntask: nothing\n") == []


def test_first_open():
    def q(*statuses):
        return [Task(id=f"T{i}", title="", line=i, status=s) for i, s in enumerate(statuses)]

    assert tasks.first_open(q("done", "skip", "pending", "pending")).id == "T2"
    assert tasks.first_open(q("done", "failed", "pending")).status == "failed"
    assert tasks.first_open(q("done", "skip")) is None
    assert tasks.first_open([]) is None


# --- parity with the v0 parser ---------------------------------------------------------------


@pytest.fixture(scope="module")
def legacy_parser():
    spec = importlib.util.spec_from_file_location("legacy_orkestra", LEGACY)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up there
    try:
        spec.loader.exec_module(module)
        yield module.gorevleri_oku
    finally:
        del sys.modules[spec.name]


V0_STATUS = {"bekliyor": "pending", "tamam": "done", "basarisiz": "failed", "atla": "skip"}
V0_TYPE = {"kod": "code", "test": "test", "dokuman": "docs"}

V0_SAMPLES = {
    "todo": (DATA / "todo_v0_TASKS.md").read_text("utf-8"),
    "template": (ROOT / "legacy/qwen-kalip/ortak/docs/TASKS.md").read_text("utf-8"),
    "edge": (
        "## T1: a\ndurum: başarısız\ntip: dokümantasyon\ndosyalar: a.py,, b.py\n"
        "dosyalar:\n- c.py\ngörev: one\n- bullet in task\n\nthree\nkabul: inline\n- more\n"
        "## T2. b\nDurum: Atlandı\nkabul:\n* star bullet\nnot a bullet\n"
        "## T3: c\ndurum: belki\n"
    ),
}


@pytest.mark.parametrize("name", V0_SAMPLES)
def test_same_result_as_v0_parser(name, legacy_parser, tmp_path):
    path = tmp_path / "TASKS.md"
    path.write_text(V0_SAMPLES[name], encoding="utf-8")
    old, new = legacy_parser(path), tasks.load(path)
    assert [t.id for t in new] == [g.kimlik for g in old]
    for g, t in zip(old, new, strict=True):
        assert t.title == g.baslik
        assert t.line == g.baslik_satiri + 1
        assert t.status == V0_STATUS.get(g.durum, g.durum)
        assert t.status_line == (None if g.durum_satiri is None else g.durum_satiri + 1)
        assert t.type == V0_TYPE.get(g.tip, g.tip)
        assert t.files == g.dosyalar
        assert t.task == g.gorev
        assert t.acceptance == g.kabul


# --- writing the status ----------------------------------------------------------------------


def test_set_status_english(tmp_path):
    path = tmp_path / "TASKS.md"
    path.write_text(ENGLISH)
    set_status(path, "T1", "done")
    head = "## T1: Parse lines\nstatus: "
    assert path.read_text() == ENGLISH.replace(head + "pending", head + "done")


def test_set_status_keeps_v0_language(tmp_path):
    path = tmp_path / "TASKS.md"
    original = (DATA / "todo_v0_TASKS.md").read_text("utf-8")
    path.write_text(original, encoding="utf-8")
    set_status(path, "T2", "failed")
    expected = original.replace(
        "## T2: Load and save the todo file\ndurum: bekliyor",
        "## T2: Load and save the todo file\ndurum: basarisiz",
    )
    assert path.read_text("utf-8") == expected
    assert [t.status for t in tasks.load(path)] == ["pending", "failed", "pending", "pending"]


def test_set_status_inserts_missing_line_and_keeps_indent(tmp_path):
    path = tmp_path / "TASKS.md"
    path.write_text("## T1: a\ntask: x\n## T2: b\n  status: pending\n## T3: c")
    set_status(path, "T1", "skip")
    set_status(path, "T2", "done")
    set_status(path, "T3", "failed")
    assert path.read_text() == (
        "## T1: a\nstatus: skip\ntask: x\n## T2: b\n  status: done\n## T3: c\nstatus: failed\n"
    )


def test_set_status_ignores_commented_example(tmp_path):
    path = tmp_path / "TASKS.md"
    path.write_text(ENGLISH)
    with pytest.raises(KeyError):
        set_status(path, "T9", "done")
    assert path.read_text() == ENGLISH


def test_set_status_rejects_unknown_status(tmp_path):
    path = tmp_path / "TASKS.md"
    path.write_text(ENGLISH)
    with pytest.raises(ValueError):
        set_status(path, "T1", "tamam")


# --- lint ------------------------------------------------------------------------------------


def codes(text):
    return [(i.severity, i.code, i.task_id) for i in lint(text)[1]]


def test_lint_clean():
    assert codes(ENGLISH) == []
    assert codes((DATA / "todo_v0_TASKS.md").read_text("utf-8")) == []


BROKEN = """\
## T1: a
status: maybe
type: script
task:
## T1: again
task: x
acceptance: y
files: /etc/passwd, ../up.py, ok/../../x.py, C:\\x.py, ~/x, src/fine..py
##T 3 broken
## T4: finished long ago
status: done
"""


def test_lint_finds_problems():
    assert codes(BROKEN) == [
        ("error", "unknown_status", "T1"),
        ("error", "unknown_type", "T1"),
        ("error", "empty_task", "T1"),
        ("error", "no_acceptance", "T1"),
        ("warning", "no_files", "T1"),
        ("error", "duplicate_id", "T1"),
        *[("error", "path_outside", "T1")] * 5,
        ("warning", "bad_heading", None),
    ]


def test_lint_empty_file():
    assert codes("# Tasks\n") == [("warning", "no_tasks", None)]


def test_every_lint_code_has_a_message():
    issues = lint(BROKEN)[1] + lint("")[1]
    for lang in i18n.SUPPORTED:
        for issue in issues:
            assert f"tasks.lint.{issue.code}" in i18n.catalog(lang)
            assert f"tasks.severity_{issue.severity}" in i18n.catalog(lang)


# --- jigw tasks lint -------------------------------------------------------------------------


def test_cli_lint_clean(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "TASKS.md").write_text(ENGLISH)
    assert main(["tasks", "lint"]) == 0
    assert capsys.readouterr().out == "tasks: 2, errors: 0, warnings: 0\n"


def test_cli_lint_reports_with_location(tmp_path, capsys):
    path = tmp_path / "T.md"
    path.write_text("## T1: a\nstatus: maybe\ntask: x\nacceptance: y\nfiles: a.py\n")
    assert main(["tasks", "lint", str(path)]) == 1
    assert capsys.readouterr().out == (
        f"{path}:1: T1: error: unknown status 'maybe' (pending | done | failed | skip)\n"
        "tasks: 1, errors: 1, warnings: 0\n"
    )


def test_cli_lint_warnings_only_pass(tmp_path, capsys):
    path = tmp_path / "T.md"
    path.write_text("## T1: a\ntask: x\nacceptance: y\n")
    assert main(["tasks", "lint", str(path)]) == 0
    assert "warning: no 'files:' listed" in capsys.readouterr().out


def test_cli_lint_turkish(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("JIGWORK_LANG", "tr")
    path = tmp_path / "T.md"
    path.write_text("## T1: a\ntask: x\n")
    assert main(["tasks", "lint", str(path)]) == 1
    out = capsys.readouterr().out
    assert "T1: hata: 'acceptance:' altında madde yok" in out
    assert out.endswith("görev: 1, hata: 1, uyarı: 1\n")


def test_cli_lint_missing_file(tmp_path, capsys):
    assert main(["tasks", "lint", str(tmp_path / "nope.md")]) == 1
    assert "Cannot read" in capsys.readouterr().err


def test_cli_tasks_without_subcommand_shows_usage(capsys):
    assert main(["tasks"]) == 2
    assert "lint" in capsys.readouterr().err
