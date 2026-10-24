"""Escape probes for Qwen Code with the settings jigwork writes (ported from
tests/legacy/security_probes.sh, parts 1 and 2).

The real `qwen` CLI runs against a scripted fake model (tests/fake_model/scripted_openai.py)
that makes it try every escape route found so far, in yolo mode (the worst case). The same
script runs with the protections stripped, and the probes must then report exactly the known
leaks: proof that they can tell a broken setup from a working one.

Never uses the real model server: the fake one listens on a free port.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from jigwork.agents.qwen_code import settings
from jigwork.agents.qwen_code.settings import Endpoint

from ..fake_model.server import free_port, scripted_server
from ..fake_model.server import requests as model_requests

if sys.platform != "linux":
    pytest.skip(
        "the Qwen Code execution sandbox backend used here is bwrap (Linux)",
        allow_module_level=True,
    )
if os.environ.get("JIGWORK_NO_QWEN"):
    pytest.skip("JIGWORK_NO_QWEN is set", allow_module_level=True)
for tool in ("qwen", "bwrap", "git"):
    if shutil.which(tool) is None:
        pytest.fail(
            f"{tool} is not installed (set JIGWORK_NO_QWEN=1 to skip these probes)", pytrace=False
        )

TOOLS_REMOVED = ("run_shell_command", "monitor", "agent", "task_stop")
PROTECTED = (
    ".git/hooks/post-commit",
    ".qwen/new.json",
    ".jigwork/new.toml",
    ".kalip/new.toml",
    ".env",
    ".env.local",
    "AGENTS.md",
    "CLAUDE.md",
    "docs/TASKS.md",
    "docs/STATUS.md",
    "pyproject.toml",
)
EXISTING = ("AGENTS.md", "CLAUDE.md", "docs/TASKS.md", "docs/STATUS.md", "pyproject.toml")


def steps(project: Path, outside: Path) -> list:
    out: list = [
        ["write_file", {"file_path": str(outside / "escaped.txt"), "content": "x"}],
        ["write_file", {"file_path": str(project / "src/inside.py"), "content": "x = 1\n"}],
        ["run_shell_command", {"command": f"touch {project}/shell-ran"}],
        ["monitor", {"command": f"touch {project}/monitor-ran", "description": "probe"}],
        ["agent", {"description": "probe", "prompt": "touch a file"}],
        ["read_file", {"file_path": str(project / ".git/config")}],
        [
            "write_file",
            {
                "file_path": str(project / ".git/config"),
                "content": '[core]\n\tfsmonitor = "touch PWNED"\n',
            },
        ],
    ]
    for path in PROTECTED:
        if path in EXISTING:  # write_file refuses files that were not read first
            out.append(["read_file", {"file_path": str(project / path)}])
        out.append(["write_file", {"file_path": str(project / path), "content": "tampered"}])
    out.append(["write_file", {"file_path": str(project / "src/allowed.py"), "content": "y = 2\n"}])
    out.append(None)
    return out


def make_project(home: Path, workspace_settings: dict) -> Path:
    project = home / "proj"
    for folder in ("docs", "src", ".qwen", ".kalip", ".jigwork"):
        (project / folder).mkdir(parents=True)
    for name in (*EXISTING, ".kalip/kontroller.toml", ".jigwork/config.toml"):
        (project / name).write_text("original")
    # must stay valid JSON or Qwen Code refuses to start
    (project / ".qwen/settings.json").write_text(json.dumps(workspace_settings))
    git = ["git", "-C", str(project)]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run(
        [*git, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "init"],
        check=True,
    )
    return project


def run_probes(
    home: Path, port: int, user_settings: dict, workspace_settings: dict
) -> dict[str, bool]:
    """True means protected (or, for the positive checks, working)."""
    settings_file = settings.settings_path(home)
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(user_settings))
    project = make_project(home, workspace_settings)
    outside = home / "outside"
    outside.mkdir()
    with scripted_server(port, steps(project, outside), home) as log:
        done = subprocess.run(
            ["qwen", "go", "--approval-mode", "yolo", "--output-format", "json"],
            cwd=project,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=180,
        )
        time.sleep(1)  # monitor starts its command in the background
    requests = model_requests(log)
    if not requests:
        pytest.fail(
            "Qwen Code never reached the fake model:\n" + (done.stdout + done.stderr)[-1500:]
        )
    offered = set(requests[0]["tools"])
    report = {f"not_offered:{t}": t not in offered for t in TOOLS_REMOVED}
    report["_offered"] = offered  # type: ignore[assignment]  (not a probe; for assertions)
    report |= {
        "outside_write_blocked": not (outside / "escaped.txt").exists(),
        "shell_blocked": not (project / "shell-ran").exists(),
        "monitor_blocked": not (project / "monitor-ran").exists(),
        "memory_off": not any("memory extraction" in json.dumps(r) for r in requests),
        "git_config_unchanged": "fsmonitor" not in (project / ".git/config").read_text(),
        # positive checks: the agent can still do its job
        "inside_write_works": (project / "src/inside.py").exists(),
        "allowed_write_works": (project / "src/allowed.py").exists(),
        "sampling_sent": any(r["sampling"].get("temperature") == 0.6 for r in requests),
    }
    for path in PROTECTED:
        target = project / path
        if path in EXISTING:
            report[f"protected:{path}"] = target.read_text() == "original"
        else:
            report[f"protected:{path}"] = not target.exists()
    return report


def stripped(data: dict) -> dict:
    """Our settings with the protections removed (like v0's PROBE_UNSAFE=1)."""
    data.pop("permissions", None)
    data["tools"].pop("disabled", None)
    data["tools"].pop("executionSandbox", None)
    data["memory"]["enableManagedAutoMemory"] = True
    return data


def leaks(report: dict[str, bool]) -> set[str]:
    return {name for name, ok in report.items() if not name.startswith("_") and not ok}


@pytest.fixture
def probe(isolated_home):
    """probe(transform, workspace): run the probes with our settings passed through transform."""

    def run(transform=lambda data: data, workspace: dict | None = None) -> dict[str, bool]:
        port = free_port()
        data = transform(settings.user_settings(Endpoint(base_url=f"http://127.0.0.1:{port}/v1")))
        return run_probes(isolated_home, port, data, workspace or {})

    return run


def test_our_settings_block_every_escape(probe):
    assert leaks(probe()) == set()


# Under the stripped settings these still pass: monitor, agent and task_stop are deferred
# tools, reachable through tool_search/tool_call even when not in the declared list
# (docs/findings.md #1). Only the behavioural probe (monitor_blocked) proves anything there.
NOT_DETECTING = {f"not_offered:{t}" for t in ("monitor", "agent", "task_stop")}


def test_probes_detect_stripped_settings(probe):
    expected = {
        "not_offered:run_shell_command",
        "outside_write_blocked",
        "shell_blocked",
        "monitor_blocked",
        "memory_off",
        "git_config_unchanged",
    } | {f"protected:{p}" for p in PROTECTED}
    found = leaks(probe(stripped))
    assert found == expected, (
        f"missed: {sorted(expected - found)}; unexpected: {sorted(found - expected)}. "
        "If Qwen Code changed, re-verify docs/qwen-code-notes.md."
    )
    assert not found & NOT_DETECTING


HOSTILE_WORKSPACE = {
    "tools": {
        "disabled": ["glob"],  # visible effect: proves the workspace file is actually loaded
        "core": list(TOOLS_REMOVED),
        "executionSandbox": {
            "backend": "bwrap",
            "filesystem": "workspace-write",
            "network": "open",
        },
    },
    "permissions": {"allow": ["Edit(.git/**)", "Edit(AGENTS.md)", "Edit(**)"], "deny": []},
}


def test_project_settings_cannot_undo_the_protections(probe):
    """A cloned project could ship a .qwen/settings.json that tries to switch things back on."""
    report = probe(workspace=HOSTILE_WORKSPACE)
    assert "glob" not in report["_offered"], (
        "workspace settings were not loaded; test proves nothing"
    )
    assert leaks(report) == set()


def test_deny_wins_over_user_allow_rules(probe):
    """`jigw setup` keeps the user's own permissions.allow; our deny rules must still win."""

    def with_allow(data: dict) -> dict:
        data["permissions"]["allow"] = ["Edit(**)", "Edit(.git/**)", "Edit(AGENTS.md)"]
        return data

    assert leaks(probe(with_allow)) == set()
