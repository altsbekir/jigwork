"""`jigw setup`: write the agent's user settings (merged, old file backed up)."""

from __future__ import annotations

import shutil
import sys

from jigwork.agents.qwen_code import settings
from jigwork.i18n import t


def run() -> int:
    path = settings.settings_path()
    try:
        result = settings.install(path)
    except settings.SettingsError as exc:
        print(t("config.unreadable", path=exc.path, error=exc.error), file=sys.stderr)
        print(t("setup.left_alone"), file=sys.stderr)
        return 1
    if result.backup:
        print(t("setup.merged", path=result.path, backup=result.backup))
    else:
        print(t("setup.written", path=result.path))
    failed = [c for c in settings.check(settings.load(path)) if not c.ok]
    for item in failed:
        print("  - " + t(f"check.{item.key}"), file=sys.stderr)
    if not shutil.which("bwrap"):
        print(t("chat.no_bwrap"), file=sys.stderr)
    return 1 if any(c.required for c in failed) else 0
