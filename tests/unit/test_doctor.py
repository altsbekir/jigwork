import json
import os

import pytest

from jigwork import cli, i18n
from jigwork.agents.qwen_code import QwenCode, settings
from jigwork.commands import doctor as commands_doctor
from jigwork.doctor import agent_probe, box_probe, system
from jigwork.servers.health import DOWN, READY, Probe


def test_os_cpu_memory_parsers(tmp_path):
    (tmp_path / "os-release").write_text('NAME="CachyOS"\nPRETTY_NAME="CachyOS Linux"\n')
    one = "model name\t: 12th Gen Intel(R) Core(TM) i7-12700H\nflags\t\t: fpu sse avx2\n"
    (tmp_path / "cpuinfo").write_text(f"processor\t: 0\n{one}\nprocessor\t: 1\n{one}")
    (tmp_path / "meminfo").write_text("MemTotal:       32571112 kB\nMemFree: 1 kB\n")
    assert system.os_name(tmp_path / "os-release") == "CachyOS Linux"
    assert system.cpu(tmp_path / "cpuinfo") == (
        "12th Gen Intel(R) Core(TM) i7-12700H",
        2,
        {"fpu", "sse", "avx2"},
    )
    assert round(system.memory_gib(tmp_path / "meminfo"), 1) == 31.1
    assert system.os_name(tmp_path / "missing") == "?"
    assert system.memory_gib(tmp_path / "missing") is None


@pytest.fixture
def fake_tool(tmp_path, monkeypatch):
    """fake_tool(name, output, code=0): an executable first on PATH."""
    bin_dir = tmp_path / "tools"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

    def make(name, output, code=0):
        script = bin_dir / name
        script.write_text(f"#!/bin/sh\ncat <<'EOF'\n{output}\nEOF\nexit {code}\n")
        script.chmod(0o755)

    return make


def test_gpus(fake_tool):
    fake_tool("nvidia-smi", "NVIDIA GeForce RTX 4060 Laptop GPU, 8188, 1034, 580.95")
    assert system.gpus() == [
        {
            "name": "NVIDIA GeForce RTX 4060 Laptop GPU",
            "total": "8188",
            "used": "1034",
            "driver": "580.95",
        }
    ]


def test_missing_required_tool_is_a_failure(fake_tool, monkeypatch):
    real = system.version
    monkeypatch.setattr(
        system, "version", lambda tool, *a: None if tool == "bwrap" else real(tool, *a)
    )
    facts = {f.fields.get("name"): f.status for f in system.facts() if f.key == "tool"}
    assert facts["bwrap"] == system.FAIL


def test_other_qwen_version_is_a_warning(fake_tool):
    fake_tool("qwen", "0.27.1")
    keys = [(f.key, f.status) for f in system.facts()]
    assert ("qwen_version", system.WARN) in keys


def test_every_probe_has_a_message():
    names = [
        *agent_probe.SECURITY,
        *agent_probe.WORKING,
        "memory_off",
        *box_probe.PROBES,
        *box_probe.WORKING,
    ]
    for lang in i18n.SUPPORTED:
        for name in names:
            key = (
                "probe.protected"
                if name.startswith("protected:")
                else ("probe.not_offered" if name.startswith("not_offered:") else f"probe.{name}")
            )
            assert key in i18n.catalog(lang), (lang, name)


NOTHING = Probe(DOWN)


def run_doctor(capsys, probe=NOTHING, agent=None):
    code = commands_doctor.run(live=False, agent=agent or QwenCode(), probe_fn=lambda url: probe)
    return code, capsys.readouterr().out


def test_no_settings_is_a_problem(isolated_home, capsys):
    code, out = run_doctor(capsys)
    assert code == 1
    assert "jigw setup" in out and "Skipped (--no-live)" in out


def test_good_settings(isolated_home, capsys):
    settings.install(settings.settings_path())
    code, out = run_doctor(capsys, Probe(READY, context=65536, slots=1, model="qwen3.6-35b-a3b"))
    assert "✘ tools.disabled" not in out and "✔ tools.disabled must include" in out
    assert "Context: the server has 65536, the agent expects 65536" in out
    assert "Server at http://127.0.0.1:8091/v1: ready" in out
    _, out = run_doctor(capsys, Probe(DOWN))
    assert "Server at http://127.0.0.1:8091/v1: not running" in out
    agent_lines = out.split("Agent settings")[1].split("Live test")[0]
    assert "✘" not in agent_lines


def test_small_server_context_is_a_problem(isolated_home, capsys):
    settings.install(settings.settings_path())
    code, out = run_doctor(capsys, Probe(READY, context=8192))
    assert code == 1 and "✘ Context: the server has 8192" in out


def test_mcp_servers_are_flagged(isolated_home, capsys):
    path = settings.settings_path()
    settings.install(path)
    data = settings.load(path)
    data["mcpServers"] = {"browser": {"command": "x"}}
    path.write_text(json.dumps(data))
    _, out = run_doctor(capsys)
    assert "! MCP servers are configured (browser)" in out


def test_turkish(isolated_home, capsys, monkeypatch):
    monkeypatch.setenv("JIGWORK_LANG", "tr")
    _, out = run_doctor(capsys)
    assert "Sistem ve araçlar" in out and "Sorun:" in out


def test_cli(monkeypatch):
    seen = []
    monkeypatch.setattr(commands_doctor, "run", lambda live=True: seen.append(live) or 0)
    assert cli.main(["doctor"]) == 0 and cli.main(["doctor", "--no-live"]) == 0
    assert seen == [True, False]
