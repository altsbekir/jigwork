"""`jigw chat`: an interactive agent session with the same restrictions as `jigw run`.

Port of v0 `qwen-guvenli`: refuse yolo mode, verify the agent's security settings and the
sandbox, refuse to start outside a git project, warn on a dirty tree, then watch .git/config
and hooks around the session and offer to restore them.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from jigwork import ui
from jigwork.agents.qwen_code import QwenCode
from jigwork.commands import common
from jigwork.core import git_guard
from jigwork.i18n import t
from jigwork.servers.health import is_healthy


def preflight(agent: QwenCode, cwd: Path, args: list[str]) -> str | None:
    """None if the session may start; otherwise the reason, already printed."""
    if refused := agent.refused_args(args):
        common.err(t("chat.no_yolo", args=" ".join(refused)))
        return "yolo"
    if not common.sandbox_ready():
        return "bwrap"
    if not common.agent_ready(agent):
        return "agent"
    home = (agent.home or Path.home()).resolve()
    here = cwd.resolve()
    if here in (home, Path("/")):
        common.err(t("chat.wrong_dir"))
        return "dir"
    top = common.toplevel(here)
    if top is None:
        common.err(t("chat.not_git"))
        return "git"
    if home.is_relative_to(top.resolve()):
        common.err(t("chat.home_repo", path=top))
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

    if not common.server_ready(agent, health=lambda url: is_healthy(url)):
        return 1

    snapshot = git_guard.GitSnapshot(cwd)
    status = agent.chat(cwd, args)

    if snapshot.changed():
        common.err("\n" + t("chat.git_changed"))
        for line in snapshot.diff():
            common.err("  " + line)
        if ui.confirm(t("chat.restore_confirm"), default=True, read=read):
            snapshot.restore()
            print(t("chat.restored"))
        else:
            common.err(t("chat.not_restored", path=snapshot.git_dir))
    return status
