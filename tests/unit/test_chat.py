import json
import subprocess
from pathlib import Path

import pytest

from jigwork.agents.qwen_code import QwenCode, settings
from jigwork.commands import chat

from .conftest import FAKE_QWEN

FSMONITOR = '[core]\n\tfsmonitor = "touch /tmp/pwned"\n'


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def project(isolated_home, monkeypatch):
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "t")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "t@example.invalid")
    settings.install(settings.settings_path())
    path = isolated_home / "proj"
    path.mkdir()
    git(path, "init", "-q")
    (path / "AGENTS.md").write_text("rules\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "init")
    monkeypatch.setattr(chat, "is_healthy", lambda url: True)
    return path


def answers(*values):
    it = iter(values)
    return lambda prompt: next(it)


def start(project, args=(), read=None):
    agent = QwenCode(executable=str(FAKE_QWEN))
    return chat.run(list(args), cwd=project, agent=agent, read=read or answers())


def test_clean_session_passes_args_and_exit_code(project, fake_qwen, capsys):
    argv_file = fake_qwen(exit=7)
    assert start(project, ["-c", "--approval-mode", "auto-edit"]) == 7
    record = json.loads(argv_file.read_text())
    assert record == {"argv": ["-c", "--approval-mode", "auto-edit"], "cwd": str(project)}
    assert "WARNING" not in capsys.readouterr().err


@pytest.mark.parametrize("args", [["--yolo"], ["--approval-mode", "yolo"], ["-y"]])
def test_yolo_is_refused(project, fake_qwen, capsys, args):
    argv_file = fake_qwen()
    assert start(project, args) == 1
    assert "yolo" in capsys.readouterr().err
    assert not argv_file.exists()


def test_missing_security_settings_are_refused(project, fake_qwen, capsys):
    argv_file = fake_qwen()
    path = settings.settings_path()
    data = settings.load(path)
    data["tools"]["disabled"] = ["run_shell_command"]
    path.write_text(json.dumps(data))
    assert start(project) == 1
    err = capsys.readouterr().err
    assert "tools.disabled must include" in err and "jigw setup" in err
    assert not argv_file.exists()


def test_unreadable_settings_are_refused(project, fake_qwen, capsys):
    fake_qwen()
    settings.settings_path().write_text("{oops")
    assert start(project) == 1
    assert "Cannot read" in capsys.readouterr().err


def test_home_and_root_are_refused(isolated_home, project, fake_qwen, capsys):
    fake_qwen()
    assert start(isolated_home) == 1
    assert start(Path("/")) == 1
    assert capsys.readouterr().err.count("home folder or in /") == 2


def test_non_git_folder_is_refused(isolated_home, project, fake_qwen, capsys):
    fake_qwen()
    plain = isolated_home / "plain"
    plain.mkdir()
    assert start(plain) == 1
    assert "not a git repository" in capsys.readouterr().err


def test_repo_containing_home_is_refused(isolated_home, project, fake_qwen, capsys):
    fake_qwen()
    git(isolated_home, "init", "-q")  # a dotfiles repo at ~
    sub = isolated_home / "notes"
    sub.mkdir()
    assert start(sub) == 1
    assert "contains your home folder" in capsys.readouterr().err


def test_dirty_tree_asks_and_default_is_no(project, fake_qwen, capsys):
    argv_file = fake_qwen()
    (project / "wip.py").write_text("")
    assert start(project, read=answers("")) == 1
    assert "Cancelled" in capsys.readouterr().out
    assert not argv_file.exists()
    assert start(project, read=answers("y")) == 0
    assert argv_file.exists()


def test_server_down(project, fake_qwen, monkeypatch, capsys):
    argv_file = fake_qwen()
    monkeypatch.setattr(chat, "is_healthy", lambda url: False)
    assert start(project) == 1
    assert "http://127.0.0.1:8091/v1" in capsys.readouterr().err
    assert not argv_file.exists()


def test_missing_agents_md_is_only_a_note(project, fake_qwen, capsys):
    fake_qwen()
    git(project, "rm", "-q", "AGENTS.md")
    git(project, "commit", "-q", "-m", "rm")
    assert start(project) == 0
    assert "no AGENTS.md" in capsys.readouterr().out


def test_tampered_git_config_is_restored_by_default(project, fake_qwen, capsys):
    config = project / ".git/config"
    before = config.read_text()
    fake_qwen(append={str(config): FSMONITOR})
    assert start(project, read=answers("")) == 0
    captured = capsys.readouterr()
    assert "WARNING" in captured.err and "+\tfsmonitor" in captured.err
    assert config.read_text() == before
    assert "restored" in captured.out


def test_tampered_hook_kept_when_user_says_no(project, fake_qwen, capsys):
    hook = project / ".git/hooks/post-checkout"
    fake_qwen(append={str(hook): "#!/bin/sh\nevil\n"})
    assert start(project, read=answers("n")) == 0
    assert hook.exists()
    assert "Inspect" in capsys.readouterr().err


def test_turkish_prompts(project, fake_qwen, monkeypatch, capsys):
    monkeypatch.setenv("JIGWORK_LANG", "tr")
    config = project / ".git/config"
    before = config.read_text()
    fake_qwen(append={str(config): FSMONITOR})
    prompts = []

    def read(prompt):
        prompts.append(prompt)
        return "e"

    assert start(project, read=read) == 0
    assert prompts == ["Eski haline döndürülsün mü? [E/h] "]
    assert config.read_text() == before


@pytest.mark.parametrize(
    ("argv", "passed"),
    [
        (["chat"], []),
        (["chat", "-c"], ["-c"]),
        (["chat", "--approval-mode", "yolo"], ["--approval-mode", "yolo"]),
        (["chat", "--", "-h"], ["-h"]),
        (["chat", "-y", "x"], ["-y", "x"]),
    ],
)
def test_cli_passes_chat_args_through(monkeypatch, argv, passed):
    from jigwork import cli

    seen = []
    monkeypatch.setattr(chat, "run", lambda args: seen.append(args) or 0)
    assert cli.main(argv) == 0
    assert seen == [passed]


def test_cli_chat_help_is_ours(capsys):
    from jigwork import cli

    with pytest.raises(SystemExit):
        cli.main(["chat", "--help"])
    assert "interactive agent session" in capsys.readouterr().out
