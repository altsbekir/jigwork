"""Escape probes for Qwen Code with the settings jigwork writes (jigwork/doctor/agent_probe.py).

The real `qwen` CLI runs against a scripted fake model that makes it try every escape route
found so far, in yolo mode (the worst case). The same probes run with the protections
stripped and must then report exactly the known leaks: proof that they can tell a broken
setup from a working one. `jigw doctor` runs the same probes with the user's own settings.
Never uses the real model server: the fake one listens on a free port.
"""

from __future__ import annotations

import os
import shutil
import sys

import pytest

from jigwork.agents.qwen_code import settings
from jigwork.doctor import agent_probe
from jigwork.doctor.agent_probe import PROTECTED, SECURITY, TOOLS_REMOVED

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


@pytest.fixture
def probe(isolated_home):
    """probe(transform, workspace): the probes with jigwork's settings passed through transform."""

    def run(transform=lambda data: data, workspace: dict | None = None) -> agent_probe.Result:
        home = isolated_home / "probe-home"
        home.mkdir()
        return agent_probe.run(home, transform(settings.user_settings()), workspace)

    return run


def test_our_settings_block_every_escape(probe):
    result = probe()
    assert result.leaks() == set()
    assert any(r["sampling"].get("temperature") == 0.6 for r in result.requests)


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
    found = probe(agent_probe.stripped).leaks()
    assert found == expected, (
        f"missed: {sorted(expected - found)}; unexpected: {sorted(found - expected)}. "
        "If Qwen Code changed, re-verify docs/qwen-code-notes.md."
    )
    assert not found & NOT_DETECTING
    assert set(SECURITY) <= found  # every security probe fired


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
    result = probe(workspace=HOSTILE_WORKSPACE)
    assert "glob" not in result.offered, "workspace settings were not loaded; test proves nothing"
    assert result.leaks() == set()


def test_deny_wins_over_user_allow_rules(probe):
    """`jigw setup` keeps the user's own permissions.allow; our deny rules must still win."""

    def with_allow(data: dict) -> dict:
        data["permissions"]["allow"] = ["Edit(**)", "Edit(.git/**)", "Edit(AGENTS.md)"]
        return data

    assert probe(with_allow).leaks() == set()


def test_mcp_servers_are_not_started_by_the_probe(probe, isolated_home):
    marker = isolated_home / "mcp-started"

    def with_mcp(data: dict) -> dict:
        data["mcpServers"] = {"x": {"command": "sh", "args": ["-c", f"touch {marker}"]}}
        return data

    assert probe(with_mcp).leaks() == set()
    assert not marker.exists()
