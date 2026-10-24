"""docs/TASKS.md: parse tasks, update their status, and lint them.

A task is a `## T<n>: <title>` heading followed by fields:

    status: pending            pending | done | failed | skip
    type: code                 code | test | docs
    files: src/a.py, tests/test_a.py
    task: What to do. Continues on the following lines.
    acceptance:
    - a measurable criterion

The v0 Turkish names (durum, tip, dosyalar, gorev, kabul; bekliyor, tamam, basarisiz, atla;
kod, dokuman) are accepted too, and a status is written back in the language its task uses.
HTML comments are ignored; any other heading ends the current task.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

PENDING, DONE, FAILED, SKIP = "pending", "done", "failed", "skip"
STATUSES = (PENDING, DONE, FAILED, SKIP)
TYPES = ("code", "test", "docs")

FIELD_ALIASES = {
    "status": "status",
    "durum": "status",
    "type": "type",
    "tip": "type",
    "files": "files",
    "dosyalar": "files",
    "task": "task",
    "gorev": "task",
    "görev": "task",
    "acceptance": "acceptance",
    "kabul": "acceptance",
}
LEGACY_FIELDS = {"durum", "tip", "dosyalar", "gorev", "görev", "kabul"}

STATUS_ALIASES = {
    **{s: s for s in STATUSES},
    "bekliyor": PENDING,
    "tamam": DONE,
    "basarisiz": FAILED,
    "başarısız": FAILED,
    "atla": SKIP,
    "atlandi": SKIP,
    "atlandı": SKIP,
}
LEGACY_STATUS = {PENDING: "bekliyor", DONE: "tamam", FAILED: "basarisiz", SKIP: "atla"}

TYPE_ALIASES = {
    **{t: t for t in TYPES},
    "kod": "code",
    "dokuman": "docs",
    "doküman": "docs",
    "dokumantasyon": "docs",
    "dokümantasyon": "docs",
}

HEADER = re.compile(r"^##\s+(T\d+)\s*[:.-]\s*(.+?)\s*$", re.I)
ANY_HEADING = re.compile(r"^#{1,6}\s")
TASK_LIKE_HEADING = re.compile(r"^##\s*T\s*\d", re.I)
FIELD = re.compile(rf"^({'|'.join(FIELD_ALIASES)})\s*:\s*(.*)$", re.I)
BULLET = re.compile(r"^[-*]\s+(.*)$")
COMMENT = re.compile(r"<!--.*?-->", re.S)


@dataclass
class Task:
    id: str
    title: str
    line: int  # 1-based line of the heading
    status: str = PENDING  # one of STATUSES, or the raw (lower-cased) value if unknown
    status_line: int | None = None
    type: str = "code"  # one of TYPES, or the raw value if unknown
    files: list[str] = field(default_factory=list)
    task: str = ""
    acceptance: list[str] = field(default_factory=list)
    legacy: bool = False  # written with the v0 Turkish field names


@dataclass(frozen=True)
class Issue:
    """A lint finding. `code` names an i18n message `tasks.lint.<code>`; `fields` fill it."""

    severity: str  # "error" or "warning"
    code: str
    line: int
    task_id: str | None = None
    fields: dict[str, str] = field(default_factory=dict)


def _strip_comments(text: str) -> str:
    """Remove HTML comments, keeping line numbers."""
    return COMMENT.sub(lambda m: "\n" * m.group().count("\n"), text)


def parse(text: str) -> list[Task]:
    tasks: list[Task] = []
    current: Task | None = None
    key: str | None = None
    for number, raw in enumerate(_strip_comments(text).splitlines(), start=1):
        if header := HEADER.match(raw):
            current = Task(id=header.group(1).upper(), title=header.group(2), line=number)
            tasks.append(current)
            key = None
            continue
        if ANY_HEADING.match(raw):
            current, key = None, None
            continue
        if current is None:
            continue
        line = raw.strip()
        if match := FIELD.match(line):
            name, value = match.group(1).lower(), match.group(2).strip()
            key = FIELD_ALIASES[name]
            current.legacy |= name in LEGACY_FIELDS
            if key == "status":
                current.status = STATUS_ALIASES.get(value.lower(), value.lower())
                current.status_line = number
            elif key == "type":
                current.type = TYPE_ALIASES.get(value.lower(), value.lower())
            elif key == "files":
                current.files += [f.strip() for f in value.split(",") if f.strip()]
            elif key == "task":
                current.task = value
            elif key == "acceptance" and value:
                current.acceptance.append(value)
            continue
        if not line:
            continue
        bullet = BULLET.match(line)
        if key == "acceptance" and bullet:
            current.acceptance.append(bullet.group(1))
        elif key == "files" and bullet:
            current.files.append(bullet.group(1).strip())
        elif key == "task":
            current.task = f"{current.task}\n{line}" if current.task else line
    return tasks


def load(path: Path) -> list[Task]:
    return parse(path.read_text(encoding="utf-8"))


def first_open(tasks: list[Task]) -> Task | None:
    """The head of the queue: the first task that is neither done nor skipped.

    If it is not pending (failed, or an unknown status), the run must stop there: later tasks
    usually build on earlier ones.
    """
    return next((t for t in tasks if t.status not in (DONE, SKIP)), None)


def set_status(path: Path, task_id: str, status: str) -> Task:
    """Write `status` for task `task_id` in place, re-reading the file first."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    text = path.read_text(encoding="utf-8")
    task = next((t for t in parse(text) if t.id == task_id), None)
    if task is None:
        raise KeyError(task_id)
    lines = text.splitlines(keepends=True)
    if task.legacy:
        new = f"durum: {LEGACY_STATUS[status]}\n"
    else:
        new = f"status: {status}\n"
    if task.status_line is not None:
        old = lines[task.status_line - 1]
        indent = old[: len(old) - len(old.lstrip())]
        lines[task.status_line - 1] = indent + new
    else:
        if not lines[task.line - 1].endswith("\n"):
            lines[task.line - 1] += "\n"
        lines.insert(task.line, new)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(lines), encoding="utf-8")
    tmp.replace(path)
    task.status = status
    return task


def _bad_path(name: str) -> bool:
    if name.startswith(("/", "\\", "~")) or re.match(r"^[A-Za-z]:", name):
        return True
    return ".." in PurePosixPath(name.replace("\\", "/")).parts


def lint(text: str) -> tuple[list[Task], list[Issue]]:
    tasks = parse(text)
    issues: list[Issue] = []

    for number, raw in enumerate(_strip_comments(text).splitlines(), start=1):
        if TASK_LIKE_HEADING.match(raw) and not HEADER.match(raw):
            issues.append(Issue("warning", "bad_heading", number, fields={"text": raw.strip()}))

    seen: dict[str, int] = {}
    for task in tasks:

        def add(severity: str, code: str, task: Task = task, **fields: str) -> None:
            issues.append(Issue(severity, code, task.line, task.id, fields))

        if task.id in seen:
            add("error", "duplicate_id", first=str(seen[task.id]))
        seen.setdefault(task.id, task.line)
        if task.status not in STATUSES:
            add("error", "unknown_status", value=task.status, allowed=" | ".join(STATUSES))
        if task.status in (DONE, SKIP):
            continue  # finished tasks block nothing; only identity problems matter for them
        if task.type not in TYPES:
            add("error", "unknown_type", value=task.type, allowed=" | ".join(TYPES))
        if not task.task.strip():
            add("error", "empty_task")
        if not task.acceptance:
            add("error", "no_acceptance")
        if not task.files:
            add("warning", "no_files")
        for name in task.files:
            if _bad_path(name):
                add("error", "path_outside", path=name)

    if not tasks:
        issues.append(Issue("warning", "no_tasks", 1))
    issues.sort(key=lambda i: (i.line, i.severity != "error"))
    return tasks, issues
