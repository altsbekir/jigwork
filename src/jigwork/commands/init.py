"""`jigw init [--type T] [folder]`: a new project from a template, or adopt an existing folder.

An empty or missing folder becomes a new project with its first commit (v0 `yeni-proje`).
A folder with files is adopted: missing files are added, nothing is overwritten, nothing is
committed (v0 `kalip-ekle`).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from jigwork import PROJECT_DIR
from jigwork.agents.qwen_code import QwenCode
from jigwork.commands import common
from jigwork.core import scaffold
from jigwork.i18n import t


def run(folder: str | None, project_type: str, agent: QwenCode | None = None) -> int:
    agent = agent or QwenCode()
    root = Path(folder).expanduser().absolute() if folder else Path.cwd()
    home = Path.home().resolve()
    if root.resolve() in (home, Path("/")) or home.is_relative_to(root.resolve()):
        common.err(t("init.wrong_dir"))
        return 1
    if (root / ".kalip").is_dir():
        common.err(t("init.v0_project"))
        return 1
    if (root / PROJECT_DIR / "config.toml").exists():
        common.err(t("init.already", path=root))
        return 1
    if root.exists() and not root.is_dir():
        common.err(t("init.not_a_folder", path=root))
        return 1
    new = not root.exists() or not any(root.iterdir())
    if new and not scaffold.NAME.match(root.name):
        common.err(t("init.bad_name", name=root.name))
        return 1

    plan = scaffold.plan(root, project_type)
    root.mkdir(parents=True, exist_ok=True)
    written = scaffold.apply(plan)
    created, skipped = agent.install_project(root, plan.skills)
    written += created
    skipped = plan.skipped + skipped

    if new:
        git = ["git", "-C", str(root)]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True)
        message = f"Create project from the jigwork template (type: {project_type})"
        if (
            subprocess.run([*git, "commit", "-q", "-m", message], capture_output=True).returncode
            != 0
        ):
            common.err(t("run.commit_failed", error=""))
        print(t("init.created", name=plan.name, type=project_type))
        print(t("init.next_steps", path=root))
        return 0

    print(t("init.adopted", type=project_type, count=len(written)))
    for rel in written:
        print(f"  + {rel}")
    if skipped:
        print(t("init.skipped"))
        for rel in skipped:
            print(f"  = {rel}")
    if plan.agents_extra:
        print(t("init.agents_extra"))
        print("".join(f"    {line}\n" for line in plan.agents_extra.splitlines()), end="")
    if common.toplevel(root) is None:
        print(t("init.not_git"))
    print(t("init.review"))
    return 0
