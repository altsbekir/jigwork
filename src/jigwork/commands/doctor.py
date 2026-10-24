"""`jigw doctor [--no-live]`: what this machine has, and whether every protection holds here.

The live part runs the real `qwen` with the user's own settings (copied into a throw-away
HOME, pointed at a scripted fake model) and the real check box with the user's real HOME
(docs/architecture.md, security invariant 6).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from jigwork import profiles
from jigwork.agents.qwen_code import QwenCode, settings
from jigwork.core.checks import cache_dir
from jigwork.doctor import agent_probe, box_probe
from jigwork.doctor.system import FAIL, INFO, OK, WARN, Fact, facts
from jigwork.i18n import t
from jigwork.servers import health
from jigwork.servers.llama_cpp import LlamaCpp

MARKS = {OK: "✔", WARN: "!", FAIL: "✘", INFO: "·"}
COLORS = {OK: "32", WARN: "33", FAIL: "31", INFO: "0"}


def _line(fact: Fact) -> str:
    text = f"  {MARKS[fact.status]} " + t(f"doctor.{fact.key}", **fact.fields)
    if sys.stdout.isatty() and fact.status != INFO:
        text = f"\033[{COLORS[fact.status]}m{text}\033[0m"
    return text


def server_facts(agent: QwenCode, probe_fn=health.probe) -> list[Fact]:
    try:
        profile = profiles.load()
    except profiles.ProfileError as exc:
        return [Fact("profile_bad", FAIL, {"error": str(exc)})]
    server = LlamaCpp(profile)
    out = [Fact("profile", INFO, {"name": profile.name})]
    out.append(
        Fact(
            "model_file", OK if profile.model_file.exists() else WARN, {"path": profile.model_file}
        )
    )
    if server.binary.exists():
        out.append(Fact("llama_binary", OK, {"path": server.binary}))
        out.append(
            Fact("llama_cuda", OK, {}) if server.has_cuda() else Fact("llama_no_cuda", WARN, {})
        )
        out.append(
            Fact("llama_fit", OK, {}) if server.has_fit() else Fact("llama_no_fit", WARN, {})
        )
    else:
        out.append(Fact("llama_binary_missing", WARN, {"path": server.binary}))
    service = server.service
    if service.available() and service.exists():
        key = "service_active" if service.is_active() else "service_inactive"
        out.append(Fact(key, INFO, {"name": service.service}))
    url = agent.model_url() or profile.base_url
    state = probe_fn(url)
    out.append(Fact("server_state", INFO, {"url": url, "state": t(f"state.{state.state}")}))
    expected = agent.model_context()
    if state.context and expected:
        status = OK if state.context >= expected else FAIL
        out.append(Fact("server_context", status, {"server": state.context, "agent": expected}))
    return out


def agent_facts(agent: QwenCode) -> tuple[list[Fact], dict | None]:
    path = settings.settings_path(agent.home)
    try:
        current = agent.settings()
    except settings.SettingsError as exc:
        return [Fact("settings_unreadable", FAIL, {"path": exc.path, "error": exc.error})], None
    if not current:
        return [Fact("settings_missing", FAIL, {"path": path})], None
    out = [Fact("settings", INFO, {"path": path})]
    for check in settings.check(current):
        status = OK if check.ok else (FAIL if check.required else WARN)
        out.append(Fact("setting", status, {"text": t(f"check.{check.key}")}))
    if current.get("mcpServers"):
        out.append(Fact("mcp_servers", WARN, {"names": ", ".join(sorted(current["mcpServers"]))}))
    return out, current


def live_agent(user_settings: dict, qwen: str = "qwen") -> list[Fact]:
    with tempfile.TemporaryDirectory(prefix="jigwork-doctor-") as home:
        try:
            result = agent_probe.run(Path(home), user_settings, qwen=qwen)
        except (agent_probe.ProbeError, OSError) as exc:
            return [Fact("live_error", FAIL, {"error": str(exc)})]
    out = []
    for name in (*agent_probe.SECURITY, *agent_probe.WORKING):
        out.append(Fact("probe", OK if result.probes[name] else FAIL, {"text": _probe_text(name)}))
    if not result.probes["memory_off"]:
        out.append(Fact("probe", WARN, {"text": _probe_text("memory_off")}))
    return out


def live_box(home: Path | None = None) -> list[Fact]:
    home = home or Path.home()
    try:
        with box_probe.layout(home, cache_dir() / "doctor") as lay:
            report = box_probe.run(lay)
    except (box_probe.ProbeError, OSError, ValueError) as exc:
        return [Fact("live_error", FAIL, {"error": str(exc)})]
    return [
        Fact("probe", OK if report[name] else FAIL, {"text": _probe_text(name)})
        for name in (*box_probe.PROBES, *box_probe.WORKING)
    ]


def _probe_text(name: str) -> str:
    if name.startswith("protected:"):
        return t("probe.protected", path=name.split(":", 1)[1])
    if name.startswith("not_offered:"):
        return t("probe.not_offered", tool=name.split(":", 1)[1])
    return t(f"probe.{name}")


def run(live: bool = True, agent: QwenCode | None = None, probe_fn=health.probe) -> int:
    agent = agent or QwenCode()
    sections: list[tuple[str, list[Fact]]] = [("doctor.section_system", facts())]
    sections.append(("doctor.section_server", server_facts(agent, probe_fn)))
    agent_list, user_settings = agent_facts(agent)
    sections.append(("doctor.section_agent", agent_list))
    if live:
        if user_settings is not None and agent.available():
            sections.append(
                ("doctor.section_live_agent", live_agent(user_settings, agent.executable))
            )
        else:
            sections.append(("doctor.section_live_agent", [Fact("live_skipped", WARN, {})]))
        sections.append(("doctor.section_live_box", live_box()))
    else:
        sections.append(("doctor.section_live_agent", [Fact("live_off", WARN, {})]))

    all_facts = [f for _, items in sections for f in items]
    for title, items in sections:
        print("\n" + t(title))
        for fact in items:
            print(_line(fact))
    failed = sum(f.status == FAIL for f in all_facts)
    warnings = sum(f.status == WARN for f in all_facts)
    print("\n" + t("doctor.summary", failed=failed, warnings=warnings))
    return 1 if failed else 0
