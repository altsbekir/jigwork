"""`jigw chat`: an interactive agent session with the same restrictions as `jigw run`.

Port of v0 `qwen-guvenli`: refuse yolo mode, verify the agent's security settings and the
sandbox, refuse to start outside a git project, warn on a dirty tree, then watch .git/config
and hooks around the session and offer to restore them.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from jigwork import ui
from jigwork.agents.qwen_code import QwenCode, settings
from jigwork.core import git_guard
from jigwork.i18n import t
from jigwork.servers.health import is_healthy


def _err(message: str) -> None:
    print(message, file=sys.stderr)


def _toplevel(cwd: Path) -> Path | None:
    done = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    return Path(done.stdout.strip()) if done.returncode == 0 else None


def preflight(agent: QwenCode, cwd: Path, args: list[str]) -> str | None:
    """None if the session may start; otherwise the reason, already printed."""
    if refused := agent.refused_args(args):
        _err(t("chat.no_yolo", args=" ".join(refused)))
        return "yolo"
    if not shutil.which("bwrap"):
        _err(t("chat.no_bwrap"))
        return "bwrap"
    if not agent.available():
        _err(t("chat.no_agent"))
        return "agent"
    try:
        current = agent.settings()
    except settings.SettingsError as exc:
        _err(t("config.unreadable", path=exc.path, error=exc.error))
        return "settings"
    missing = [c for c in settings.check(current) if c.required and not c.ok]
    if missing:
        _err(t("chat.insecure", path=settings.settings_path(agent.home)))
        for item in missing:
            _err("  - " + t(f"check.{item.key}"))
        _err(t("chat.run_setup"))
        return "insecure"
    home = (agent.home or Path.home()).resolve()
    here = cwd.resolve()
    if here in (home, Path("/")):
        _err(t("chat.wrong_dir"))
        return "dir"
    top = _toplevel(here)
    if top is None:
        _err(t("chat.not_git"))
        return "git"
    if home.is_relative_to(top.resolve()):
        _err(t("chat.home_repo", path=top))
        return "home-repo"
    return None


def run(
    args: list[str],
    cwd: Path | None = None,
    agent: QwenCode | None = None,
    read: Callable[[str], str] = input,
) -> int:
    agent = agent or QwenCode()
    cwd = cwd or Path.cwd()
    if preflight(agent, cwd, args) is not None:
        return 1

    dirty = git_guard.changed_files(cwd)
    if dirty:
        print(t("chat.dirty"))
        for name in dirty[:5]:
            print(f"  {name}")
        if not ui.confirm(t("chat.dirty_confirm"), default=False, read=read):
            print(t("chat.cancelled"))
            return 1
    if not (cwd / "AGENTS.md").is_file():
        print(t("chat.no_agents_md"))

    url = settings.base_url(agent.settings())
    if url is None or not is_healthy(url):
        _err(t("chat.server_down", url=url or "?"))
        return 1

    snapshot = git_guard.GitSnapshot(cwd)
    status = agent.chat(cwd, args)

    if snapshot.changed():
        _err("\n" + t("chat.git_changed"))
        for line in snapshot.diff():
            _err("  " + line)
        if ui.confirm(t("chat.restore_confirm"), default=True, read=read):
            snapshot.restore()
            print(t("chat.restored"))
        else:
            _err(t("chat.not_restored", path=snapshot.git_dir))
    return status
