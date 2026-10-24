"""`jigw init`: create a project from a template, or adopt an existing folder.

Templates (package data, `jigwork/templates/`): `_base/` plus one folder per project type.
Special files in a template: `AGENTS.extra.md` (lines for the "## Stack" section of AGENTS.md),
`gitignore.lines` (merged into .gitignore), `skills/` (installed by the agent adapter).
`{{PROJECT_NAME}}` is replaced in every text file. Nothing that exists is ever overwritten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from jigwork import PROJECT_DIR
from jigwork.core.project import PROJECT_TYPES, render_config, type_defaults

PLACEHOLDER = "{{PROJECT_NAME}}"
SPECIAL = {"AGENTS.extra.md", "gitignore.lines", "skills"}
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def templates() -> Traversable:
    return resources.files("jigwork") / "templates"


CACHES = {"__pycache__", ".ruff_cache", ".pytest_cache", ".mypy_cache"}


def _walk(root: Traversable, prefix: str = ""):
    for entry in sorted(root.iterdir(), key=lambda e: e.name):
        if entry.name in CACHES:  # tool caches must never be copied into a project
            continue
        rel = f"{prefix}{entry.name}"
        if entry.is_dir():
            yield from _walk(entry, rel + "/")
        else:
            yield rel, entry


@dataclass
class Plan:
    root: Path
    name: str
    project_type: str
    files: dict[str, str] = field(default_factory=dict)  # path -> content, to create
    skipped: list[str] = field(default_factory=list)  # exist already: left alone
    gitignore_lines: list[str] = field(default_factory=list)  # to append to .gitignore
    agents_extra: str = ""  # Stack lines, when AGENTS.md exists and is not ours to change
    skills: list[tuple[str, dict[str, str]]] = field(default_factory=list)  # (name, files)


def plan(root: Path, project_type: str, name: str | None = None) -> Plan:
    if project_type not in PROJECT_TYPES:
        raise ValueError(project_type)
    name = name or root.name
    result = Plan(root, name, project_type)
    layers = [templates() / "_base", templates() / project_type]
    files: dict[str, str] = {}
    extra = ""
    lines: list[str] = []
    for layer in layers:
        for rel, entry in _walk(layer):
            top = rel.split("/", 1)[0]
            if top in SPECIAL:
                continue
            files[rel] = entry.read_text(encoding="utf-8")  # a type's file replaces the base one
        if (layer / "AGENTS.extra.md").is_file():
            extra = (layer / "AGENTS.extra.md").read_text(encoding="utf-8")
        if (layer / "gitignore.lines").is_file():
            lines += (layer / "gitignore.lines").read_text(encoding="utf-8").splitlines()
        if (layer / "skills").is_dir():
            for skill in sorted((layer / "skills").iterdir(), key=lambda e: e.name):
                body = {rel: entry.read_text(encoding="utf-8") for rel, entry in _walk(skill)}
                result.skills.append((skill.name, body))
    files[f"{PROJECT_DIR}/config.toml"] = render_config(type_defaults(project_type), project_type)

    agents_is_new = not (root / "AGENTS.md").exists()
    if agents_is_new:
        files["AGENTS.md"] = files["AGENTS.md"].rstrip("\n") + "\n" + extra
    else:
        result.agents_extra = extra
    for rel, content in files.items():
        if (root / rel).exists():
            result.skipped.append(rel)
        else:
            result.files[rel] = content.replace(PLACEHOLDER, name)

    present = set()
    if (root / ".gitignore").exists():
        present = {
            ln.strip() for ln in (root / ".gitignore").read_text(encoding="utf-8").splitlines()
        }
    result.gitignore_lines = [
        ln for ln in lines if ln.startswith("#") or (ln.strip() and ln.strip() not in present)
    ]
    if all(ln.startswith("#") for ln in result.gitignore_lines):
        result.gitignore_lines = []
    return result


def apply(p: Plan) -> list[str]:
    """Write the plan; returns the paths created or changed (relative to the root)."""
    written = []
    for rel, content in p.files.items():
        path = p.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(rel)
    if p.gitignore_lines:
        path = p.root / ".gitignore"
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        sep = "" if not old or old.endswith("\n\n") else ("\n" if old.endswith("\n") else "\n\n")
        path.write_text(old + sep + "\n".join(p.gitignore_lines) + "\n", encoding="utf-8")
        written.append(".gitignore")
    return written
