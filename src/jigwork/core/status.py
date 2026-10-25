"""docs/STATUS.md: one table row per finished task attempt run.

New files get an English header. A v0 file (Turkish header) keeps getting Turkish result words,
like TASKS.md keeps its field language (see core/tasks.py).
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class Row:
    result: str  # "done" or "failed" (v0 words translated)
    attempts: int
    note: str


def latest_rows(path: Path) -> dict[str, Row]:
    """The last row of each task (a task run again gets a new row)."""
    if not path.exists():
        return {}
    words = {v: k for k, v in V0_RESULTS.items()}
    latest: dict[str, Row] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if (
            len(cells) != 5
            or not cells[1]
            or cells[0] in ("Date", "Tarih")
            or set(cells[0]) <= {"-"}
        ):
            continue
        attempts = int(cells[3]) if cells[3].isdigit() else 0
        latest[cells[1].split()[0]] = Row(words.get(cells[2], cells[2]), attempts, cells[4])
    return latest


def review_marks(path: Path) -> set[str]:
    """Task ids whose latest row is "done" with a human-review note."""
    return {
        i for i, row in latest_rows(path).items() if row.result == DONE and REVIEW_MARK in row.note
    }
