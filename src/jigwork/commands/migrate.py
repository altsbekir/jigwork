"""`jigw migrate [--apply]`: show what turning a v0 project into v1 changes, then do it."""

from __future__ import annotations

from pathlib import Path

from jigwork.commands import common
from jigwork.core import git_guard, migrate
from jigwork.core import project as project_config
from jigwork.i18n import t


def run(apply: bool = False, cwd: Path | None = None) -> int:
    root = common.toplevel(cwd or Path.cwd())
    if root is None:
        common.err(t("run.not_git"))
        return 1
    try:
        plan = migrate.plan(root)
    except migrate.MigrateError as error:
        common.err(t(error.key, **error.fields))
        return 1
    print(t("migrate.plan_title", path=root))
    for key, fields in plan.notes:
        print("  - " + t(key, **fields))
    if not apply:
        print(t("migrate.dry_run"))
        return 0

    migrate.apply(plan)
    project_config.load(root)  # the result must load as a v1 project
    git_guard.git(root, "add", "-A")
    body = "\n".join("- " + t(key, **fields) for key, fields in plan.notes)
    done = git_guard.git(
        root, "commit", "-q", "-m", "Migrate project to jigwork v1", "-m", body, check=False
    )
    if git_guard.changed_files(root):
        common.err(t("run.commit_failed", error=done))
        return 1
    print(t("migrate.done"))
    return 0
