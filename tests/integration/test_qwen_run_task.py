"""QwenCode.run_task end to end: the real `qwen` CLI, our settings, a scripted fake model."""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from jigwork.agents.base import Limits
from jigwork.agents.qwen_code import QwenCode, settings
from jigwork.agents.qwen_code.settings import Endpoint
from jigwork.doctor.fake_model import ScriptedModel, free_port

if os.environ.get("JIGWORK_NO_QWEN"):
    pytest.skip("JIGWORK_NO_QWEN is set", allow_module_level=True)
for tool in ("qwen", "bwrap", "git"):
    if shutil.which(tool) is None:
        pytest.fail(f"{tool} is not installed (set JIGWORK_NO_QWEN=1 to skip)", pytrace=False)


@pytest.fixture
def setup(isolated_home):
    project = isolated_home / "proj"
    (project / "src").mkdir(parents=True)
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    return None, project


SHORT = Limits("2m", 20)


def run(_port, project, steps, limits=SHORT):
    events = []
    with ScriptedModel(steps) as model:
        settings.install(settings.settings_path(), Endpoint(base_url=model.base_url))
        result = QwenCode().run_task(
            project,
            "## Task T1: probe",
            limits,
            project / ".jigwork/work/log/T1.jsonl",
            events.append,
        )
    return result, events, model.requests


def test_structured_report(setup):
    port, project = setup
    target = project / "src/a.py"
    steps = [
        ["write_file", {"file_path": str(target), "content": "a = 1\n"}],
        [
            "structured_output",
            {"changed": ["src/a.py"], "done": "Wrote a.", "needs": [], "doubts": "none"},
        ],
    ]
    result, events, log = run(port, project, steps)
    assert result.ok, result.error
    assert result.report.changed == ["src/a.py"] and result.report.done == "Wrote a."
    assert result.report.needs == [] and result.report.doubts == []
    assert [(e.name, e.target) for e in events] == [("write_file", "src/a.py")]
    assert result.tool_calls == 2
    assert target.read_text() == "a = 1\n"
    assert "structured_output" in log[0]["tools"]
    assert set(log[0]["tools"]).isdisjoint({"run_shell_command", "monitor", "agent", "task_stop"})


def test_plain_text_answer_falls_back(setup):
    port, project = setup
    result, events, _ = run(port, project, [None])  # the fake model just says "done"
    assert result.ok, result.error
    assert result.report.done == "done"
    assert events == []


def test_tool_call_limit(setup):
    port, project = setup
    steps = [["list_directory", {"path": str(project)}]] * 5
    result, _, _ = run(port, project, steps, Limits("2m", 1))
    assert (result.ok, result.error) == (False, "limit")


def test_unreachable_model_server_is_a_connection_error(isolated_home):
    """The loop's outage handling depends on this (Qwen Code retries ~70 s, then gives up)."""
    port = free_port()  # nothing listens here
    settings.install(settings.settings_path(), Endpoint(base_url=f"http://127.0.0.1:{port}/v1"))
    project = isolated_home / "proj"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    result = QwenCode().run_task(
        project, "## Task T1: probe", SHORT, project / "log.jsonl", lambda e: None
    )
    assert (result.ok, result.connection_error) == (False, True), result.error
    assert result.report.done == ""  # the error text is not taken for a report
