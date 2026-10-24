import subprocess
import sys
from pathlib import Path

import pytest

from jigwork.core import checks
from jigwork.core.project import type_defaults


def test_dependencies(tmp_path):
    assert checks.dependencies(tmp_path) == []
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["rich>=13", "click"]\n')
    assert checks.dependencies(tmp_path) == ["rich>=13", "click"]


def test_venv_lives_in_the_cache_outside_the_project(tmp_path, isolated_home):
    venv = checks.venv_path(tmp_path / "todo")
    assert venv.parent == isolated_home / ".cache/jigwork/venv"
    assert venv.name.startswith("todo-")
    assert not venv.is_relative_to(tmp_path / "todo")


def test_venv_python_is_never_under_home(monkeypatch, isolated_home):
    inside = isolated_home / ".local/share/uv/python/bin/python3"
    monkeypatch.setattr(sys, "_base_executable", str(inside), raising=False)
    monkeypatch.setattr(sys, "executable", str(inside))
    chosen = checks.venv_python()
    assert not Path(chosen).resolve().is_relative_to(isolated_home)


def test_venv_python_prefers_the_running_base_interpreter(monkeypatch):
    monkeypatch.setattr(sys, "_base_executable", "/usr/bin/python3", raising=False)
    assert checks.venv_python() == "/usr/bin/python3"


@pytest.fixture
def fake_pip(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[1:3] == ["-m", "venv"]:
            Path(argv[3], "bin").mkdir(parents=True)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(checks.subprocess, "run", run)
    return calls


def test_prepare_venv_builds_once_and_rebuilds_when_dependencies_change(tmp_path, fake_pip):
    project = tmp_path / "p"
    project.mkdir()
    (project / "pyproject.toml").write_text('[project]\ndependencies = ["rich"]\n')
    built = []
    venv = checks.prepare_venv(project, on_build=built.append)
    assert built == [["rich"]]
    assert fake_pip[1][-3:] == ["pytest", "ruff", "rich"]
    assert checks.prepare_venv(project, on_build=built.append) == venv
    assert len(built) == 1
    (project / "pyproject.toml").write_text('[project]\ndependencies = ["rich", "click"]\n')
    checks.prepare_venv(project, on_build=built.append)
    assert built[-1] == ["rich", "click"]


def test_prepare_venv_reports_pip_failure(tmp_path, monkeypatch):
    def run(argv, **kwargs):
        if argv[1:3] == ["-m", "venv"]:
            Path(argv[3], "bin").mkdir(parents=True)
            return subprocess.CompletedProcess(argv, 0)
        return subprocess.CompletedProcess(argv, 1)

    monkeypatch.setattr(checks.subprocess, "run", run)
    with pytest.raises(checks.PrepareError):
        checks.prepare_venv(tmp_path)


# --- requests that only repeat the checks --------------------------------------------------

PYTHON_TOOLS = checks.check_tools(type_defaults("python"))


def test_check_tools_of_the_python_defaults():
    assert PYTHON_TOOLS == {"ruff", "pytest"}


@pytest.mark.parametrize(
    "command",
    [
        "pytest tests/test_cli.py",
        "cd ~/Projeler/todo && pytest tests/test_cli.py",  # from the step-12 bench run
        "ruff check src/todo/cli.py tests/test_cli.py",
        "python -m pytest -q",
        "python3 -m pytest; ruff check .",
        "uv run pytest",
        "PYTHONPATH=src pytest -x",
    ],
)
def test_only_checks(command):
    assert checks.only_checks(command, PYTHON_TOOLS)


@pytest.mark.parametrize(
    "command",
    [
        "pip install rich",
        "python -m pip install rich",
        "python script.py",
        "cd src",
        "pytest && rm -rf build",
        "pytest | tee out.txt",
        "pytest > out.txt",
        "pytest $(cat args)",
        "pytest `x`",
        "pytest 'unclosed",
        "",
    ],
)
def test_real_requests(command):
    assert not checks.only_checks(command, PYTHON_TOOLS)
