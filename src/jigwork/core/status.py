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
REVIEW_MARK = "human review"  # in the note of a task accepted with signs of weakened tests


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


def review_marks(path: Path) -> set[str]:
    """Task ids whose latest row is "done" with a human-review note."""
    if not path.exists():
        return set()
    latest: dict[str, tuple[str, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if (
            len(cells) != 5
            or not cells[1]
            or cells[0] in ("Date", "Tarih")
            or set(cells[0]) <= {"-"}
        ):
            continue
        task_id = cells[1].split()[0]
        latest[task_id] = (cells[2], cells[4])
    done = {DONE, V0_RESULTS[DONE]}
    return {i for i, (result, note) in latest.items() if result in done and REVIEW_MARK in note}
