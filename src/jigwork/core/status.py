"""docs/STATUS.md: one table row per finished task attempt run.

New files get an English header. A v0 file (Turkish header) keeps getting Turkish result words,
like TASKS.md keeps its field language (see core/tasks.py).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jigwork.core.tasks import DONE, FAILED, Task

HEADER = "| Date | Task | Result | Attempts | Note |\n|---|---|---|---|---|\n"
V0_MARKER = "| Tarih |"
V0_RESULTS = {DONE: "tamam", FAILED: "başarısız"}


def _cell(text: str) -> str:
    return text.replace("|", "/").replace("\r", " ").replace("\n", " ")


def append_row(
    path: Path,
    task: Task,
    result: str,
    attempts: int,
    note: str,
    when: datetime | None = None,
) -> None:
    if result not in (DONE, FAILED):
        raise ValueError(f"unknown result {result!r}")
    text = path.read_text(encoding="utf-8") if path.exists() else HEADER
    if text and not text.endswith("\n"):
        text += "\n"
    word = V0_RESULTS[result] if V0_MARKER in text else result
    when = when or datetime.now()
    text += (
        f"| {when:%Y-%m-%d %H:%M} | {task.id} {_cell(task.title)} | {word} | {attempts} "
        f"| {_cell(note)} |\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
