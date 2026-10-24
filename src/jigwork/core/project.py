"""A jigwork project: where its files are and its config, with defaults.

v1 projects keep their config in `.jigwork/config.toml` (English keys). v0 projects keep it in
`.kalip/kontroller.toml` (Turkish keys) until `jigw migrate`; they also keep their v0 work dir
`.kalip/calisma/`, because that is what their .gitignore ignores.

```toml
[prepare]
kind = "python-venv"        # or "none"; default: python-venv when pyproject.toml exists
[autofix]
command = "ruff format ..." # runs in the box before the checks
[checks]                    # in order; the first failure stops the rest
lint = "ruff check ."
[skills]                    # skill folder patterns per task type, and "fix" for fix attempts
code = ["python-code"]
[limits]
attempts = 3                # first attempt + fixes
agent_wall_time = "45m"
agent_tool_calls = 80
check_timeout = 600         # seconds per check command
```
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from jigwork import PROJECT_DIR
from jigwork.core.prompts import DEFAULT_SKILLS

PYTHON_AUTOFIX = "ruff format --no-cache --quiet . ; ruff check --no-cache --fix --quiet . ; true"
PREPARE_KINDS = ("python-venv", "none")

V0_DIR = ".kalip"
V0_SKILL_TYPES = {"kod": "code", "test": "test", "dokuman": "docs", "duzeltme": "fix"}
V0_LIMITS = {
    "max_deneme": "attempts",
    "qwen_sure": "agent_wall_time",
    "max_arac": "agent_tool_calls",
    "kontrol_sure_sn": "check_timeout",
}
V0_PREPARE = {"yok": "none", "python-venv": "python-venv"}


class ConfigError(Exception):
    def __init__(self, path: Path, error: str) -> None:
        super().__init__(f"{path}: {error}")
        self.path = path
        self.error = error


@dataclass
class Limits:
    attempts: int = 3
    agent_wall_time: str = "45m"
    agent_tool_calls: int = 80
    check_timeout: int = 600


@dataclass
class Config:
    prepare: str = "none"
    autofix: str = ""
    checks: dict[str, str] = field(default_factory=dict)
    skills: dict[str, list[str]] = field(default_factory=dict)
    limits: Limits = field(default_factory=Limits)


@dataclass
class Project:
    root: Path
    config: Config
    config_path: Path | None  # None: no config file, defaults only
    legacy: bool  # a v0 project (.kalip/)

    @property
    def tasks_path(self) -> Path:
        return self.root / "docs" / "TASKS.md"

    @property
    def status_path(self) -> Path:
        return self.root / "docs" / "STATUS.md"

    @property
    def work_dir(self) -> Path:
        return self.root / (f"{V0_DIR}/calisma" if self.legacy else f"{PROJECT_DIR}/work")

    @property
    def log_dir(self) -> Path:
        return self.work_dir / "log"


def _v0_to_v1(data: dict) -> dict:
    out: dict = {}
    if isinstance(data.get("hazirlik"), dict) and "tur" in data["hazirlik"]:
        kind = str(data["hazirlik"]["tur"])
        out["prepare"] = {"kind": V0_PREPARE.get(kind, kind)}
    if isinstance(data.get("oto_duzeltme"), dict) and "komut" in data["oto_duzeltme"]:
        out["autofix"] = {"command": data["oto_duzeltme"]["komut"]}
    if "kontroller" in data:
        out["checks"] = data["kontroller"]
    if isinstance(data.get("skills"), dict):
        out["skills"] = {V0_SKILL_TYPES.get(k, k): v for k, v in data["skills"].items()}
    if isinstance(data.get("orkestra"), dict):
        out["limits"] = {V0_LIMITS.get(k, k): v for k, v in data["orkestra"].items()}
    return out


def _build(root: Path, data: dict, path: Path | None) -> Config:
    def table(name: str) -> dict:
        value = data.get(name, {})
        if not isinstance(value, dict):
            raise ConfigError(path or root, f"[{name}] must be a table")
        return value

    config = Config()
    kind = table("prepare").get(
        "kind", "python-venv" if (root / "pyproject.toml").exists() else "none"
    )
    if kind not in PREPARE_KINDS:
        raise ConfigError(path or root, f"[prepare] kind must be one of {', '.join(PREPARE_KINDS)}")
    config.prepare = kind
    autofix = table("autofix")
    if "command" in autofix:
        config.autofix = str(autofix["command"])
    elif kind == "python-venv":
        config.autofix = PYTHON_AUTOFIX
    for name, command in table("checks").items():
        if not isinstance(command, str):
            raise ConfigError(path or root, f"[checks] {name} must be a string")
        config.checks[name] = command
    config.skills = {k: list(v) for k, v in DEFAULT_SKILLS.items()}
    for kind_name, patterns in table("skills").items():
        if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
            raise ConfigError(path or root, f"[skills] {kind_name} must be a list of strings")
        config.skills[kind_name] = patterns
    limits = table("limits")
    try:
        config.limits = Limits(
            attempts=int(limits.get("attempts", 3)),
            agent_wall_time=str(limits.get("agent_wall_time", "45m")),
            agent_tool_calls=int(limits.get("agent_tool_calls", 80)),
            check_timeout=int(limits.get("check_timeout", 600)),
        )
    except (TypeError, ValueError) as exc:
        raise ConfigError(path or root, f"[limits] {exc}") from exc
    if config.limits.attempts < 1:
        raise ConfigError(path or root, "[limits] attempts must be at least 1")
    return config


def load(root: Path) -> Project:
    v1 = root / PROJECT_DIR / "config.toml"
    v0 = root / V0_DIR / "kontroller.toml"
    legacy = not v1.exists() and (root / V0_DIR).is_dir()
    path = v1 if v1.exists() else v0 if v0.exists() else None
    data: dict = {}
    if path is not None:
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(path, str(exc)) from exc
        if path == v0:
            data = _v0_to_v1(data)
    return Project(root, _build(root, data, path), path, legacy)


# --- writing a config (jigw init, jigw migrate) -----------------------------------------------

PROJECT_TYPES = ("python", "c-cpp", "generic")


def type_defaults(project_type: str) -> Config:
    """The config a new project of this type starts with."""
    skills = {"code": [], "test": [], "docs": [], "fix": ["fix-failing-checks"]}
    if project_type == "python":
        return Config(
            prepare="python-venv",
            autofix=PYTHON_AUTOFIX,
            checks={
                "lint": "ruff check --no-cache .",
                "test": "python -m pytest -q -p no:cacheprovider",
            },
            skills={**skills, "code": ["python-code", "python-test"], "test": ["python-test"]},
        )
    if project_type == "c-cpp":
        build = (
            "cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug -DCMAKE_COMPILE_WARNING_AS_ERROR=ON"
            " > /dev/null && cmake --build build -j"
        )
        return Config(
            checks={
                "build": build,
                "test": "ctest --test-dir build --output-on-failure --no-tests=error",
            },
            skills={**skills, "code": ["c-cpp-code", "c-cpp-test"], "test": ["c-cpp-test"]},
        )
    if project_type == "generic":
        return Config(skills=skills)
    raise ValueError(f"unknown project type {project_type!r}")


def _toml(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml(v) for v in value) + "]"
    return json.dumps(str(value), ensure_ascii=False)  # a valid TOML basic string


def _key(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z0-9_-]+", name) else json.dumps(name, ensure_ascii=False)


def render_config(config: Config, project_type: str) -> str:
    lines = [
        "# jigwork project settings. Checks run in a sandbox: no network, no view of your home.",
        "",
        "[project]",
        f"type = {_toml(project_type)}",
        "",
        "[prepare]",
        "# python-venv: a test environment outside the project (~/.cache/jigwork/venv/) with",
        "# pytest, ruff and the [project] dependencies of pyproject.toml; rebuilt on change.",
        f"kind = {_toml(config.prepare)}",
        "",
        "[autofix]",
        "# Runs in the sandbox before the checks: mechanical fixes (formatting, import order)",
        "# that should never cost the model an attempt.",
    ]
    lines.append(f"command = {_toml(config.autofix)}" if config.autofix else '# command = "..."')
    lines += [
        "",
        "[checks]",
        "# In order; the first failure stops the rest and its output goes to the model.",
    ]
    if config.checks:
        lines += [f"{_key(name)} = {_toml(command)}" for name, command in config.checks.items()]
    else:
        lines.append("# No checks: tasks are accepted on the agent's word. Example:")
        lines.append('# test = "make test"')
    lines += [
        "",
        "[skills]",
        "# Skills put into the prompt, by task type (folder names of skills).",
    ]
    lines += [f"{_key(kind)} = {_toml(patterns)}" for kind, patterns in config.skills.items()]
    limits = config.limits
    lines += [
        "",
        "[limits]",
        f"attempts = {limits.attempts}  # the first attempt + fixes",
        f"agent_wall_time = {_toml(limits.agent_wall_time)}",
        f"agent_tool_calls = {limits.agent_tool_calls}",
        f"check_timeout = {limits.check_timeout}  # seconds per check command",
        "",
    ]
    return "\n".join(lines)
