"""`jigw migrate`: turn a v0 project (`.kalip/`, Turkish field names) into a v1 one.

`plan()` reads the project and computes every new file content without writing anything;
`apply()` writes them and the caller commits. What changes:
* `.kalip/kontroller.toml` (+ `.kalip/tip`) -> `.jigwork/config.toml` with English keys
* `.kalip/calisma/` (logs, patches) -> `.jigwork/work/`; `.kalip/` is removed
* docs/TASKS.md: v0 field names and values -> English (the rest of each line stays)
* docs/STATUS.md: header, result column and the notes jigwork/v0 wrote -> English
* .gitignore: `.kalip/calisma/` -> `.jigwork/work/`
* the v0 template's Turkish comments, where they are unchanged, -> the v1 template's English
AGENTS.md, CLAUDE.md, GEMINI.md and `.qwen/` are not touched.

The Turkish strings below are data: they match what v0 wrote, nothing else uses them.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from jigwork import PROJECT_DIR
from jigwork.core import git_guard, tasks
from jigwork.core.project import V0_DIR, ConfigError, load, render_config
from jigwork.core.status import HEADER as V1_STATUS_HEADER

V0_TYPES = {"genel": "generic", "python": "python", "c-cpp": "c-cpp"}

# --- v0 template comments and their v1 replacements ------------------------------------------

V0_TASKS_COMMENT = """<!--
Görevleri bu yorumun ALTINA yaz (ya da Claude/GPT'ye yazdır). Kurallar:
- Her görev tek, küçük, tek başına test edilebilir bir iş olsun (ideal: 1-3 dosya).
- "dosyalar": modelin okuyacağı/değiştireceği dosyalar.
- "kabul": test edilebilir, ölçülebilir maddeler.
- "tip": kod | test | dokuman  (orkestratör hangi skill'leri ekleyeceğine buna göre karar verir)
- "durum": bekliyor | tamam | basarisiz  (orkestratör günceller, sen "bekliyor" yaz)

Örnek:

## T1: Add a function that parses a todo line
durum: bekliyor
tip: kod
dosyalar: src/todo/parser.py, tests/test_parser.py
gorev: Write parse_line(text) that turns "[x] buy milk" into a Todo(done=True, title="buy milk").
kabul:
- "[ ] a" gives done=False, title="a"
- "[x] a" gives done=True
- any other format raises ValueError
- tests for all three cases exist and pass
-->"""
V0_TASKS_COMMENT_EXAMPLE = """<!--
Görev kuralları:
- Her görev tek, küçük, tek başına test edilebilir bir iş (ideal: 1-3 dosya).
- "dosyalar": modelin okuyacağı/değiştireceği dosyalar.
- "kabul": test edilebilir, ölçülebilir maddeler.
- "tip": kod | test | dokuman
- "durum": bekliyor | tamam | basarisiz  (orkestra günceller; yeni görevi "bekliyor" yaz)
-->"""
V0_STATUS_COMMENT = (
    "<!-- Orkestratör her görevden sonra buraya bir satır ekler. Elle de not düşebilirsin. -->"
)
V1_STATUS_COMMENT = "<!-- jigwork adds a row after every task. You can add notes by hand too. -->"
V0_STATUS_HEADER = "| Tarih | Görev | Sonuç | Deneme | Not |"
ARCHITECTURE_COMMENTS = {
    "<!-- Bu dosyayı projeye başlarken doldur (ya da Claude/GPT'ye doldurt).\n"
    "     Kısa tut: model bunu sık okuyacak. Her bölüm birkaç satırı geçmesin. -->": (
        "<!-- Fill this in when the project starts (or have a larger model do it).\n"
        "     Keep it short: the model reads it often. A few lines per section at most. -->"
    ),
    "<!-- 2-3 cümle: program ne yapıyor, kim kullanıyor -->": (
        "<!-- 2-3 sentences: what the program does, who uses it -->"
    ),
    "<!-- Her modül için tek satır: dosya: sorumluluğu -->": (
        "<!-- One line per module: file: what it is responsible for -->"
    ),
    '<!-- Önemli kararlar ve nedeni, tek satır. Örn: "Storage: JSON file, single user, no DB needed" -->': (
        '<!-- Important decisions and why, one line each. E.g. "Storage: JSON file, single user, no DB needed" -->'
    ),
    '<!-- Önemli kararlar ve nedeni, tek satır. Örn: "C only, no C++; no external libraries" -->': (
        '<!-- Important decisions and why, one line each. E.g. "C only, no C++; no external libraries" -->'
    ),
    "<!-- Şimdilik bilerek yapılmayanlar -->": "<!-- What is deliberately left out for now -->",
}

V1_FIELD = {
    "durum": "status",
    "tip": "type",
    "dosyalar": "files",
    "gorev": "task",
    "görev": "task",
    "kabul": "acceptance",
}
V0_FIELD_LINE = re.compile(r"^(\s*)(durum|tip|dosyalar|gorev|görev|kabul)(\s*:)(.*)$", re.I)
COMMENT = re.compile(r"<!--.*?-->", re.S)

NOTE_RULES = [  # (pattern, replacement) for the notes v0 wrote into STATUS.md
    (re.compile(r"(\d+)dk (\d+)sn"), r"\1m \2s"),
    (re.compile(r"\b(\d+)sn\b"), r"\1s"),
    (re.compile(r"(\S+) geçti\b"), r"\1 passed"),
    (re.compile(r"(\S+) başarısız\b"), r"\1 failed"),
    (re.compile(r"\bkontrol yok\b"), "no checks"),
    (re.compile(r"Qwen hiçbir dosyayı değiştirmedi"), "the agent changed no files"),
    (re.compile(r"\(şüpheler: "), "(doubts: "),
    (re.compile(r"\byama: "), "patch: "),
    (re.compile(r"\.kalip/calisma/"), f"{PROJECT_DIR}/work/"),
]
V0_RESULTS = {"tamam": "done", "başarısız": "failed", "basarisiz": "failed"}


class MigrateError(Exception):
    def __init__(self, key: str, **fields: object) -> None:
        super().__init__(key)
        self.key = key
        self.fields = fields


@dataclass
class Plan:
    root: Path
    project_type: str
    writes: dict[str, str] = field(default_factory=dict)  # path -> new content
    moves: list[tuple[str, str]] = field(default_factory=list)  # ignored work files to move
    remove_v0_dir: bool = True
    notes: list[tuple[str, dict]] = field(default_factory=list)  # (i18n key, fields), for the plan

    def note(self, key: str, **fields: object) -> None:
        self.notes.append((key, fields))


# --- the pure rewrites ------------------------------------------------------------------------


def _outside_comments(text: str, fn) -> str:
    """Apply `fn` to the text between HTML comments only."""
    out, last = [], 0
    for match in COMMENT.finditer(text):
        out.append(fn(text[last : match.start()]))
        out.append(match.group())
        last = match.end()
    out.append(fn(text[last:]))
    return "".join(out)


def _field_line(line: str) -> str:
    body = line.rstrip("\r\n")
    end = line[len(body) :]
    match = V0_FIELD_LINE.match(body)
    if not match:
        return line
    return _field(match) + end


def _field(match: re.Match) -> str:
    indent, name, colon, rest = match.groups()
    key = V1_FIELD[name.lower()]
    value = rest.strip()
    if key == "status":
        value = tasks.STATUS_ALIASES.get(value.lower(), value)
    elif key == "type":
        value = tasks.TYPE_ALIASES.get(value.lower(), value)
    else:
        return f"{indent}{key}{colon}{rest}"
    return f"{indent}{key}{colon} {value}" if value else f"{indent}{key}{colon}"


def rewrite_tasks(text: str) -> str:
    for old in (V0_TASKS_COMMENT, V0_TASKS_COMMENT_EXAMPLE):
        if old in text:
            v1 = _v1_tasks_comment() if old == V0_TASKS_COMMENT else _v1_tasks_rules()
            text = text.replace(old, v1)
    return _outside_comments(
        text, lambda part: "".join(_field_line(ln) for ln in part.splitlines(keepends=True))
    )


def _template(rel: str) -> str:
    from jigwork.core.scaffold import templates

    return (templates() / "_base" / rel).read_text(encoding="utf-8")


def _v1_tasks_comment() -> str:
    return COMMENT.search(_template("docs/TASKS.md")).group()


def _v1_tasks_rules() -> str:
    """The rules part of the v1 comment, for v0 files that had the short comment (no example)."""
    full = _v1_tasks_comment()
    return full[: full.index("\nExample:")].rstrip() + "\n-->"


def rewrite_status(text: str) -> str:
    text = text.replace(V0_STATUS_COMMENT, V1_STATUS_COMMENT)
    out = []
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\n")
        if bare.strip() == V0_STATUS_HEADER:
            out.append(V1_STATUS_HEADER.splitlines()[0] + "\n")
            continue
        cells = bare.split("|")
        if len(cells) == 7 and bare.startswith("|") and not set(bare) <= set("|- "):
            result = cells[3].strip()
            cells[3] = f" {V0_RESULTS.get(result, result)} "
            note = cells[5]
            for pattern, replacement in NOTE_RULES:
                note = pattern.sub(replacement, note)
            cells[5] = note
            out.append("|".join(cells) + ("\n" if line.endswith("\n") else ""))
            continue
        out.append(line)
    return "".join(out)


def rewrite_architecture(text: str) -> str:
    for old, new in ARCHITECTURE_COMMENTS.items():
        text = text.replace(old, new)
    return text


def rewrite_gitignore(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == f"{V0_DIR}/calisma/":
            line = f"{PROJECT_DIR}/work/"
        elif stripped.startswith("# kalıp"):
            line = line.replace("# kalıp", "# jigwork", 1)
        lines.append(line)
    if f"{PROJECT_DIR}/work/" not in (ln.strip() for ln in lines):
        lines += ["", "# jigwork", f"{PROJECT_DIR}/work/"]
    return "\n".join(lines) + "\n"


def _same_tasks(old: str, new: str) -> bool:
    def key(t: tasks.Task):  # line numbers may shift when a v0 comment block is replaced
        return (t.id, t.title, t.status, t.type, t.files, t.task, t.acceptance)

    return [key(t) for t in tasks.parse(old)] == [key(t) for t in tasks.parse(new)]


# --- plan and apply ---------------------------------------------------------------------------


def plan(root: Path) -> Plan:
    v0 = root / V0_DIR
    if (root / PROJECT_DIR / "config.toml").exists():
        raise MigrateError("migrate.already")
    if not v0.is_dir():
        raise MigrateError("migrate.not_v0")
    if git_guard.changed_files(root):
        raise MigrateError("migrate.dirty")
    if (v0 / "calisma" / "yarim.json").exists():
        raise MigrateError("migrate.resume_pending")
    try:
        project = load(root)
    except ConfigError as exc:
        raise MigrateError("run.bad_config", path=exc.path, error=exc.error) from exc

    tip = (v0 / "tip").read_text(encoding="utf-8").strip() if (v0 / "tip").exists() else ""
    default_type = "python" if (root / "pyproject.toml").exists() else "generic"
    project_type = V0_TYPES.get(tip, default_type)
    p = Plan(root, project_type)

    p.writes[f"{PROJECT_DIR}/config.toml"] = render_config(project.config, project_type)
    p.note("migrate.config", type=project_type)

    def rewrite(rel: str, fn, key: str) -> None:
        path = root / rel
        if not path.exists():
            return
        old = path.read_text(encoding="utf-8")
        new = fn(old)
        if new != old:
            p.writes[rel] = new
            p.note(key, path=rel)

    rewrite("docs/TASKS.md", rewrite_tasks, "migrate.tasks")
    if "docs/TASKS.md" in p.writes and not _same_tasks(
        (root / "docs/TASKS.md").read_text(encoding="utf-8"), p.writes["docs/TASKS.md"]
    ):
        raise MigrateError("migrate.tasks_differ")  # never write a TASKS.md that reads differently
    rewrite("docs/STATUS.md", rewrite_status, "migrate.status")
    rewrite("docs/ARCHITECTURE.md", rewrite_architecture, "migrate.architecture")
    rewrite(".gitignore", rewrite_gitignore, "migrate.gitignore")
    if not (root / ".gitignore").exists():
        p.writes[".gitignore"] = rewrite_gitignore("")
        p.note("migrate.gitignore", path=".gitignore")

    work = v0 / "calisma"
    if work.is_dir():
        for path in sorted(work.rglob("*")):
            if path.is_file():
                rel = path.relative_to(work)
                p.moves.append((str(path.relative_to(root)), f"{PROJECT_DIR}/work/{rel}"))
        if p.moves:
            p.note("migrate.work", count=len(p.moves))
    extra = v0 / "AGENTS.ek.md"
    if extra.exists():
        p.writes[f"{PROJECT_DIR}/AGENTS.extra.md"] = extra.read_text(encoding="utf-8")
        p.note("migrate.agents_extra", path=f"{PROJECT_DIR}/AGENTS.extra.md")
    p.note("migrate.remove_v0", path=f"{V0_DIR}/")
    return p


def apply(p: Plan) -> None:
    root = p.root
    for rel, content in p.writes.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for old, new in p.moves:
        target = root / new
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(root / old), str(target))
    if p.remove_v0_dir and (root / V0_DIR).exists():
        if git_guard.git(root, "ls-files", V0_DIR).strip():
            git_guard.git(root, "rm", "-r", "-q", "--cached", V0_DIR)
        shutil.rmtree(root / V0_DIR)
