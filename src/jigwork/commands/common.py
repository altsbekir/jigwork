"""Checks and output shared by the commands that start the agent or the check box."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from jigwork.agents.qwen_code import QwenCode, settings
from jigwork.core.loop import Duration
from jigwork.i18n import t

COLORS = {"title": "1", "ok": "32", "warn": "33", "error": "31", "dim": "2", "command": "1"}
MARKS = {"ok": "✔ ", "warn": "! ", "error": "✘ "}


def err(message: str) -> None:
    print(message, file=sys.stderr)


def duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return t("time.seconds", s=seconds)
    return t("time.minutes", m=seconds // 60, s=f"{seconds % 60:02d}")


def render(level: str, key: str, **fields: object) -> None:
    """Print one progress message from core (see core/loop.py) in the user's language."""
    shown = {k: duration(v) if isinstance(v, Duration) else v for k, v in fields.items()}
    message = t(key, **shown)
    body = message.lstrip(" ")
    indent = message[: len(message) - len(body)]
    text = indent + MARKS.get(level, "") + body  # "   ✔ lint", not "✔    lint"
    stream = sys.stderr if level == "error" else sys.stdout
    if level == "command":
        text = "     " + text
    if level in COLORS and stream.isatty():
        text = f"\033[{COLORS[level]}m{text}\033[0m"
    print(text, file=stream, flush=True)


def toplevel(cwd: Path) -> Path | None:
    done = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    return Path(done.stdout.strip()) if done.returncode == 0 else None


def sandbox_ready() -> bool:
    if shutil.which("bwrap"):
        return True
    err(t("chat.no_bwrap"))
    return False


def agent_ready(agent: QwenCode) -> bool:
    """The agent is installed and its user settings hold every required protection."""
    if not agent.available():
        err(t("chat.no_agent"))
        return False
    try:
        current = agent.settings()
    except settings.SettingsError as exc:
        err(t("config.unreadable", path=exc.path, error=exc.error))
        return False
    missing = [c for c in settings.check(current) if c.required and not c.ok]
    if missing:
        err(t("chat.insecure", path=settings.settings_path(agent.home)))
        for item in missing:
            err("  - " + t(f"check.{item.key}"))
        err(t("chat.run_setup"))
        return False
    return True


def server_session(agent: QwenCode, probe_fn=None, lazy: bool = False):
    """The model server for one run/chat (servers/session.py), or None after printing why."""
    from jigwork import profiles
    from jigwork.servers import session
    from jigwork.servers.llama_cpp import LlamaCpp

    url = agent.model_url()
    if url is None:
        err(t("session.no_url"))
        return None
    try:
        server = LlamaCpp(profiles.load())
    except profiles.ProfileError:
        server = None  # an external server needs no profile
    kwargs = {"probe_fn": probe_fn} if probe_fn else {}
    kwargs["lazy"] = lazy
    return session.ServerSession(
        url, server, agent.model_context(), agent.model_name(), session.policy(), render, **kwargs
    )
