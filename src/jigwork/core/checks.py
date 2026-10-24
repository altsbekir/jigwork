"""Running a project's checks in the sandbox: test environment, auto-fix, checks in order.

The Python test venv lives outside the project (`$XDG_CACHE_HOME/jigwork/venv/`) and is mounted
read-only: inside the project the agent could plant a `.pth` file that runs whenever pip runs
on the host (docs/findings.md #5). It holds pytest, ruff and the `[project].dependencies` of
pyproject.toml (a protected file) and is rebuilt when that list changes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from jigwork import NAME
from jigwork.core import git_guard
from jigwork.core.project import Config, Project
from jigwork.core.prompts import trim_output
from jigwork.sandbox.base import Sandbox
from jigwork.sandbox.bwrap import BASE_PATH


class PrepareError(Exception):
    pass


@dataclass(frozen=True)
class CheckLine:
    name: str
    passed: bool
    returncode: int
    seconds: float
    timed_out: bool = False


@dataclass
class CheckRun:
    passed: bool
    lines: list[CheckLine] = field(default_factory=list)
    failure: str = ""  # trimmed output of the failing check, for the fix prompt
    autofix_applied: bool = False
    restored: list[str] = field(default_factory=list)  # protected paths the checks changed
    no_checks: bool = False

    def summary(self) -> str:
        """For STATUS.md and commit messages (English, like every project file we write)."""
        if self.no_checks:
            return "no checks"
        return ", ".join(f"{c.name} {'passed' if c.passed else 'failed'}" for c in self.lines)


def cache_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / NAME


def venv_python() -> str:
    """An interpreter for the test venv that is visible inside the box (not under HOME)."""
    home = Path.home().resolve()
    for candidate in (getattr(sys, "_base_executable", None), sys.executable):
        if candidate and not Path(candidate).resolve().is_relative_to(home):
            return candidate
    system = shutil.which("python3", path=BASE_PATH)
    if system is None:
        raise PrepareError("no python3 outside the home folder for the test environment")
    return system


def dependencies(project: Path) -> list[str]:
    path = project / "pyproject.toml"
    if not path.exists():
        return []
    deps = (
        tomllib.loads(path.read_text(encoding="utf-8")).get("project", {}).get("dependencies", [])
    )
    return [str(d) for d in deps]


def venv_path(project: Path) -> Path:
    digest = hashlib.sha1(str(project).encode()).hexdigest()[:8]
    return cache_dir() / "venv" / f"{project.name}-{digest}"


def prepare_venv(project: Path, on_build=lambda deps: None) -> Path:
    deps = dependencies(project)
    venv = venv_path(project)
    python = venv_python()
    signature = hashlib.sha1(json.dumps([sorted(deps), python, sys.version]).encode()).hexdigest()
    marker = venv / ".jigwork-signature"
    if marker.exists() and marker.read_text() == signature:
        return venv
    on_build(deps)
    shutil.rmtree(venv, ignore_errors=True)
    venv.parent.mkdir(parents=True, exist_ok=True)
    if subprocess.run([python, "-m", "venv", str(venv)]).returncode != 0:
        raise PrepareError(f"{python} -m venv {venv} failed")
    pip = [str(venv / "bin" / "pip"), "install", "-q", "--disable-pip-version-check"]
    if subprocess.run([*pip, "pytest", "ruff", *deps]).returncode != 0:
        raise PrepareError("pip install failed (see the output above)")
    marker.write_text(signature)
    return venv


def run_checks(
    project: Project,
    sandbox: Sandbox,
    log_path: Path | None = None,
    on_build=lambda deps: None,
    on_autofix=lambda: None,
    on_line=lambda line: None,
) -> CheckRun:
    config = project.config
    if not config.checks:
        return CheckRun(passed=True, no_checks=True)
    venv = prepare_venv(project.root, on_build) if config.prepare == "python-venv" else None
    mounts = {"extra_ro_mounts": [venv], "path_prepend": [venv / "bin"]} if venv else {}
    readonly = git_guard.protected_paths(project.root)
    timeout = config.limits.check_timeout
    log: list[str] = []
    run = CheckRun(passed=True)

    if config.autofix:
        before = git_guard.worktree_signature(project.root)
        result = sandbox.run(
            project.root, config.autofix, readonly=readonly, timeout=timeout, **mounts
        )
        log.append(f"===== autofix: {config.autofix}  (exit {result.returncode})\n{result.output}")
        run.autofix_applied = git_guard.worktree_signature(project.root) != before
        if run.autofix_applied:
            on_autofix()

    for name, command in config.checks.items():
        result = sandbox.run(project.root, command, readonly=readonly, timeout=timeout, **mounts)
        output = result.output + (f"\n[timed out after {timeout} s]" if result.timed_out else "")
        log.append(
            f"===== {name}: {command}  (exit {result.returncode}, {result.seconds:.1f} s)\n{output}"
        )
        line = CheckLine(
            name, result.returncode == 0, result.returncode, result.seconds, result.timed_out
        )
        run.lines.append(line)
        on_line(line)
        if not line.passed:
            run.passed = False
            run.failure = f"$ {command}\n{trim_output(output)}"
            break  # the first failure only: one problem at a time for a small model

    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("\n".join(log), encoding="utf-8")
    # .git is read-only in the box, so running git here is safe
    run.restored = git_guard.restore_protected(project.root)
    return run


_SHELL_SPECIAL = re.compile(r"[|<>`$(){}*?\[\]!\\\n]")  # anything beyond a plain command list
_SEPARATORS = re.compile(r"\s*(?:&&|;)\s*")


def _tool(segment: str) -> str | None:
    """The program a plain command runs: `python -m pytest -q` -> pytest, `ruff check .` ->
    ruff; env assignments and `uv run` are skipped. None: `cd`, or nothing to run."""
    try:
        words = shlex.split(segment)
    except ValueError:
        return ""
    while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):
        words = words[1:]
    if words[:2] == ["uv", "run"]:
        words = words[2:]
    if not words or words[0] == "cd":
        return None
    name = Path(words[0]).name
    if re.fullmatch(r"python3?(\.\d+)?", name) and len(words) > 2 and words[1] == "-m":
        return words[2]
    return name


def check_tools(config: Config) -> set[str]:
    """The programs the project's checks and auto-fix run."""
    tools = set()
    for command in [*config.checks.values(), config.autofix or ""]:
        for segment in _SEPARATORS.split(command):
            if (tool := _tool(segment)) and tool not in ("true", "false"):
                tools.add(tool)
    return tools


def only_checks(command: str, tools: set[str]) -> bool:
    """The command only runs what the checks run anyway (agents often ask for `pytest`,
    although jigwork runs the checks itself). Anything unusual counts as a real request."""
    if _SHELL_SPECIAL.search(command):
        return False
    found = [_tool(segment) for segment in _SEPARATORS.split(command.strip())]
    run = [tool for tool in found if tool is not None]
    return bool(run) and all(tool in tools for tool in run)
