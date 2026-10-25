import subprocess

import pytest

from jigwork import cli
from jigwork.agents.qwen_code import settings
from jigwork.commands import common
from jigwork.commands import run as commands_run
from jigwork.servers.health import DOWN, READY, Probe

from .test_loop import TASKS

REAL_SANDBOX_READY = common.sandbox_ready


@pytest.fixture(autouse=True)
def bwrap_installed(monkeypatch):
    """The commands refuse to work without bwrap; these tests are about what comes after."""
    monkeypatch.setattr(common, "sandbox_ready", lambda: True)


@pytest.fixture
def project(isolated_home, monkeypatch):
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "t")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "t@example.invalid")
    root = isolated_home / "proj"
    (root / "docs").mkdir(parents=True)
    (root / "docs/TASKS.md").write_text(
        TASKS.replace("status: pending", "status: done", 1) + "## T3: Broken\n"
    )
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def test_status_lists_tasks_and_problems(project, capsys):
    assert commands_run.run("status", cwd=project) == 0
    assert capsys.readouterr().out.splitlines() == [
        " ✔ T1   done     code  Write a",
        " · T2   pending  code  Write b",
        " · T3   pending  code  Broken  ← 'task:' is empty; 'acceptance:' has no items",
    ]


def test_status_shows_resume_note(project, capsys):
    (project / ".jigwork/work").mkdir(parents=True)
    (project / ".jigwork/work/resume.json").write_text('{"task": "T2", "attempt": 1}')
    commands_run.run("status", cwd=project)
    assert "waiting to be resumed: T2" in capsys.readouterr().out


def test_not_a_git_project(isolated_home, capsys):
    (isolated_home / "plain").mkdir()
    assert commands_run.run("status", cwd=isolated_home / "plain") == 1
    assert "Not inside a git project." in capsys.readouterr().err


def test_bad_config_is_reported(project, capsys):
    (project / ".jigwork").mkdir()
    (project / ".jigwork/config.toml").write_text("[checks\n")
    assert commands_run.run("status", cwd=project) == 1
    assert "Cannot use the project config" in capsys.readouterr().err


def test_run_refuses_without_security_settings(project, capsys, monkeypatch):
    monkeypatch.setattr("jigwork.agents.qwen_code.QwenCode.available", lambda self: True)
    path = settings.settings_path()
    path.parent.mkdir()
    path.write_text("{}")
    assert commands_run.run("run", cwd=project, probe_fn=lambda url: Probe(READY)) == 1
    err = capsys.readouterr().err
    assert "Security settings are missing" in err


def test_run_refuses_when_server_is_down(project, capsys, monkeypatch):
    settings.install(settings.settings_path())
    monkeypatch.setattr("jigwork.agents.qwen_code.QwenCode.available", lambda self: True)
    assert commands_run.run("run", cwd=project, probe_fn=lambda url: Probe(DOWN)) == 1
    assert "No model server answers" in capsys.readouterr().err


def test_stop_messages_are_translated(project, capsys, monkeypatch):
    monkeypatch.setenv("JIGWORK_LANG", "tr")
    (project / "docs/TASKS.md").unlink()
    assert commands_run.run("status", cwd=project) == 1
    assert "yok. Bu bir jigwork projesi mi?" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["run"], ("run", False, False)),
        (["run", "--one"], ("run", True, False)),
        (["resume"], ("resume", False, False)),
        (["check"], ("check", False, False)),
        (["status"], ("status", False, False)),
        (["status", "--stats"], ("status", False, True)),
    ],  # fmt: skip
)
def test_cli_wiring(monkeypatch, argv, expected):
    seen = []

    def fake_run(command, one=False, stats=False):
        seen.append((command, one, stats))
        return 0

    monkeypatch.setattr(commands_run, "run", fake_run)
    assert cli.main(argv) == 0
    assert seen == [expected]


def test_render_puts_the_mark_after_the_indent(capsys):
    from jigwork.commands.common import render
    from jigwork.core.loop import Duration

    render("ok", "run.check_passed", name="lint", seconds=Duration(65), code=0)
    render("warn", "run.no_checks")
    assert capsys.readouterr().out.splitlines() == [
        "   ✔ lint (1m 05s)",
        "! This project defines no checks; the task is accepted on the agent's word.",
    ]


def test_run_refuses_without_bwrap(project, capsys, monkeypatch):
    monkeypatch.setattr(common, "sandbox_ready", REAL_SANDBOX_READY)
    monkeypatch.setattr(common.shutil, "which", lambda name: None)
    assert commands_run.run("run", cwd=project) == 1
    assert "bubblewrap (bwrap) is not installed" in capsys.readouterr().err


def test_status_shows_the_human_review_mark(project, capsys):
    (project / "docs/STATUS.md").write_text(
        "| Date | Task | Result | Attempts | Note |\n|---|---|---|---|---|\n"
        "| 2026-10-25 10:00 | T1 Write a | done | 2 | 1m 00s; human review: fix attempt 2 "
        "changed only tests (tests/test_a.py) |\n"
    )
    commands_run.run("status", cwd=project)
    assert (
        capsys.readouterr().out.splitlines()[0] == " ✔ T1   done     code  Write a  ⚑ human review"
    )


def test_status_stats(project, capsys):
    from jigwork.agents.base import AgentResult, Call, SessionStats
    from jigwork.core import stats
    from jigwork.core.report import Report
    from jigwork.servers.metrics import ServerCounters

    log = project / ".jigwork/work/log"
    session = AgentResult(True, Report(), "", 125.0, 4, stats=SessionStats([Call(9, 1, 1200)]))
    server = ServerCounters(0, 0, 0, 1200, 80.0)
    stats.write(stats.path_for(log, "T1", 1), stats.record("T1", 1, session, server))
    assert commands_run.run("status", cwd=project, stats=True) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].split() == [
        "task",
        "sessions",
        "time",
        "tokens",
        "longest",
        "tok/s",
        "text",
        "retries",
    ]
    assert out[1].split() == ["T1", "1", "2m", "05s", "1200", "1200", "15.0", "0", "0"]
    assert out[2].endswith("Agent sessions: 1, time: 2m 05s, tokens generated: 1200.")


def test_status_stats_without_runs(project, capsys):
    assert commands_run.run("status", cwd=project, stats=True) == 0
    assert "No run statistics yet" in capsys.readouterr().out
