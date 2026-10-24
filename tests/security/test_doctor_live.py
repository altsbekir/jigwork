"""`jigw doctor` verifies the protections live, and the verification fails on an unprotected
setup (docs/architecture.md, security invariant 6)."""

from __future__ import annotations

import json
import os
import shutil

import pytest

from jigwork.agents.qwen_code import QwenCode, settings
from jigwork.commands import doctor as commands_doctor
from jigwork.doctor import agent_probe
from jigwork.doctor.system import FAIL, OK
from jigwork.sandbox import bwrap
from jigwork.servers.health import DOWN, Probe

if os.environ.get("JIGWORK_NO_QWEN"):
    pytest.skip("JIGWORK_NO_QWEN is set", allow_module_level=True)
for tool in ("qwen", "bwrap", "git"):
    if shutil.which(tool) is None:
        pytest.fail(f"{tool} is not installed (set JIGWORK_NO_QWEN=1 to skip)", pytrace=False)


def statuses(facts):
    return {f.fields.get("text"): f.status for f in facts}


def test_live_agent_test_passes_with_jigwork_settings(isolated_home):
    settings.install(settings.settings_path())
    facts = commands_doctor.live_agent(QwenCode().settings())
    assert facts and all(f.status == OK for f in facts), [f for f in facts if f.status != OK]


def test_live_agent_test_fails_with_stripped_settings(isolated_home):
    settings.install(settings.settings_path())
    facts = commands_doctor.live_agent(agent_probe.stripped(QwenCode().settings()))
    failed = [text for text, status in statuses(facts).items() if status == FAIL]
    assert "run_shell_command did not run" in failed
    assert "writing outside the project is blocked" in failed
    assert ".git/config was not changed (fsmonitor escape)" in failed


def test_live_box_test_passes(isolated_home):
    facts = commands_doctor.live_box()
    assert all(f.status == OK for f in facts), [f for f in facts if f.status != OK]
    assert not (isolated_home / ".cache/jigwork/doctor").exists()  # cleaned up


def test_live_box_test_fails_with_a_network_in_the_box(isolated_home, monkeypatch):
    real = bwrap.BwrapSandbox.command

    def leaky(self, *args, **kwargs):
        argv = real(self, *args, **kwargs)
        i = argv.index("--unshare-all")
        return argv[:i] + ["--unshare-user-try", "--unshare-pid", "--unshare-ipc"] + argv[i + 1 :]

    monkeypatch.setattr(bwrap.BwrapSandbox, "command", leaky)
    failed = [
        text for text, status in statuses(commands_doctor.live_box()).items() if status == FAIL
    ]
    assert failed == ["no network"]


def test_doctor_exit_code_follows_the_live_result(isolated_home, capsys, monkeypatch):
    path = settings.settings_path()
    settings.install(path)

    def probe(url):
        return Probe(DOWN)

    commands_doctor.run(live=True, probe_fn=probe)
    out = capsys.readouterr().out
    assert "Live test: the agent cannot escape" in out
    live_part = out.split("Live test: the agent")[1]
    assert "✘" not in live_part, live_part
    path.write_text(json.dumps(agent_probe.stripped(settings.load(path))))
    assert commands_doctor.run(live=True, probe_fn=probe) == 1
    assert "✘ run_shell_command did not run" in capsys.readouterr().out
