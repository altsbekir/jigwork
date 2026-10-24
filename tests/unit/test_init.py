import json
import re
import subprocess

import pytest

from jigwork import cli
from jigwork.commands import init as commands_init
from jigwork.core import project as project_config
from jigwork.core import scaffold, tasks
from jigwork.core.project import PROJECT_TYPES, type_defaults

from .conftest import ROOT

TURKISH = re.compile("[ğüşıöçĞÜŞİÖÇ]")


@pytest.fixture(autouse=True)
def git_identity(monkeypatch):
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "t")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "t@example.invalid")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True).stdout


@pytest.mark.parametrize(
    ("template", "v0"),
    [
        ("_base/skills/fix-failing-checks", "ortak/.qwen/skills/fix-failing-checks"),
        ("python/skills/python-code", "paketler/python/.qwen/skills/python-code"),
        ("python/skills/python-test", "paketler/python/.qwen/skills/python-test"),
        ("c-cpp/skills/c-cpp-code", "paketler/c-cpp/.qwen/skills/c-cpp-code"),
        ("c-cpp/skills/c-cpp-test", "paketler/c-cpp/.qwen/skills/c-cpp-test"),
    ],
)
def test_skills_are_the_benched_v0_skills(template, v0):
    ours = (scaffold.templates() / template / "SKILL.md").read_text()
    assert ours == (ROOT / "legacy/qwen-kalip" / v0 / "SKILL.md").read_text()


@pytest.mark.parametrize("project_type", PROJECT_TYPES)
def test_everything_a_template_writes_is_english(tmp_path, project_type):
    p = scaffold.plan(tmp_path / "x", project_type)
    for rel, content in p.files.items():
        assert not TURKISH.search(content), rel
    assert "{{" not in "".join(p.files.values())


@pytest.mark.parametrize("project_type", PROJECT_TYPES)
def test_new_project(isolated_home, capsys, project_type):
    root = isolated_home / "Projects" / "demo"
    assert commands_init.run(str(root), project_type) == 0
    assert "Created 'demo'" in capsys.readouterr().out
    assert git(root, "status", "--porcelain") == ""
    assert (
        git(root, "log", "--format=%s")
        == f"Create project from the jigwork template (type: {project_type})\n"
    )
    agents = (root / "AGENTS.md").read_text()
    assert agents.startswith("# Project: demo\n") and agents.rstrip().endswith(
        (scaffold.templates() / project_type / "AGENTS.extra.md").read_text().rstrip()
    )
    assert (root / "docs/TASKS.md").read_text().startswith("# Tasks: demo\n")
    assert tasks.load(root / "docs/TASKS.md") == []  # the example sits inside a comment
    loaded = project_config.load(root)
    assert not loaded.legacy and loaded.config == type_defaults(project_type)
    assert ".jigwork/work/" in (root / ".gitignore").read_text().splitlines()
    ignored = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", ".jigwork/work/x.log"])
    assert ignored.returncode == 0
    assert (
        json.loads((root / ".qwen/settings.json").read_text())["tools"]["disabled"][0]
        == "run_shell_command"
    )
    assert (root / ".qwen/skills/fix-failing-checks/SKILL.md").exists()


def test_python_project_files(isolated_home):
    root = isolated_home / "pyproj"
    commands_init.run(str(root), "python")
    assert 'name = "pyproj"' in (root / "pyproject.toml").read_text()
    for path in ("src/.gitkeep", "tests/.gitkeep", ".qwen/skills/python-code/SKILL.md"):
        assert (root / path).exists()
    assert "src/        application code" in (root / "docs/ARCHITECTURE.md").read_text()
    assert "__pycache__/" in (root / ".gitignore").read_text()


def test_adopt_existing_folder_overwrites_nothing(isolated_home, capsys):
    root = isolated_home / "existing"
    root.mkdir()
    (root / "AGENTS.md").write_text("my own rules\n")
    (root / "pyproject.toml").write_text("[project]\nname = 'mine'\n")
    (root / ".gitignore").write_text("__pycache__/\n.venv/\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    assert commands_init.run(str(root), "python") == 0
    out = capsys.readouterr().out
    assert (root / "AGENTS.md").read_text() == "my own rules\n"
    assert (root / "pyproject.toml").read_text() == "[project]\nname = 'mine'\n"
    assert "  = AGENTS.md" in out and "  = pyproject.toml" in out
    assert "Source code in src/" in out  # the Stack lines to add by hand
    lines = (root / ".gitignore").read_text().splitlines()
    assert (
        lines.count("__pycache__/") == 1
        and lines.count(".venv/") == 1
        and ".jigwork/work/" in lines
    )
    assert git(root, "log") == ""  # nothing committed
    assert "git status" in out


def test_adopt_twice_is_refused(isolated_home, capsys):
    root = isolated_home / "p"
    commands_init.run(str(root), "generic")
    assert commands_init.run(str(root), "generic") == 1
    assert "already a jigwork project" in capsys.readouterr().err


def test_adopt_outside_git_gives_a_hint(isolated_home, capsys):
    root = isolated_home / "plain"
    root.mkdir()
    (root / "notes.txt").write_text("x")
    commands_init.run(str(root), "generic")
    assert "git init" in capsys.readouterr().out


@pytest.mark.parametrize("where", ["home", "root", "above"])
def test_refuses_home_and_root(isolated_home, capsys, where):
    folder = {"home": isolated_home, "root": "/", "above": isolated_home.parent}[where]
    assert commands_init.run(str(folder), "generic") == 1
    assert "home folder" in capsys.readouterr().err


def test_refuses_v0_project(isolated_home, capsys):
    root = isolated_home / "old"
    (root / ".kalip").mkdir(parents=True)
    assert commands_init.run(str(root), "python") == 1
    assert "jigw migrate" in capsys.readouterr().err


def test_bad_name(isolated_home, capsys):
    assert commands_init.run(str(isolated_home / "bad name"), "generic") == 1
    assert "letters, digits" in capsys.readouterr().err


def test_cli(isolated_home, monkeypatch):
    seen = []
    monkeypatch.setattr(commands_init, "run", lambda folder, kind: seen.append((folder, kind)) or 0)
    assert cli.main(["init", "x", "--type", "c-cpp"]) == 0
    assert cli.main(["init"]) == 0
    assert seen == [("x", "c-cpp"), (None, "generic")]


def test_tool_caches_in_a_template_are_never_copied(tmp_path, monkeypatch):
    fake = tmp_path / "templates"
    for layer in ("_base", "generic"):
        (fake / layer / ".ruff_cache").mkdir(parents=True)
        (fake / layer / ".ruff_cache" / "blob").write_bytes(b"\xe2\x00")
    (fake / "_base" / "AGENTS.md").write_text("# Project: {{PROJECT_NAME}}\n")
    monkeypatch.setattr(scaffold, "templates", lambda: fake)
    p = scaffold.plan(tmp_path / "x", "generic")
    assert not any(".ruff_cache" in rel for rel in p.files)
