"""The agent's final report: schema, normalisation, plain-text fallback.

The agent is asked to finish with a structured report {changed, done, needs, doubts}. Small
models say "nothing" in many ways (`["none"]`, "-", "[]"); a `needs: ["none"]` would stop the run
and ask the user to run "none" (docs/findings.md #13), so every list is normalised.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

SCHEMA = {
    "type": "object",
    "properties": {
        "changed": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Files you created or edited",
        },
        "done": {"type": "string", "description": "One or two sentences about what you did"},
        "needs": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Exact shell commands the user must run; empty list if none",
        },
        "doubts": {"type": "string", "description": 'Anything uncertain, or "none"'},
    },
    "required": ["changed", "done", "needs", "doubts"],
}

EMPTY_VALUES = {
    "",
    "none",
    "yok",
    "-",
    "n/a",
    "na",
    "null",
    "nothing",
    "no",
    "[]",
    "['none']",
    '["none"]',
}


def schema_json() -> str:
    return json.dumps(SCHEMA, indent=2) + "\n"


def clean_list(value: object) -> list[str]:
    """Items of `value` (a list or a single value) without the "nothing" placeholders."""
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    cleaned = []
    for item in items:
        text = str(item).strip().strip("`").strip()
        if text.lower() not in EMPTY_VALUES:
            cleaned.append(text)
    return cleaned


@dataclass
class Report:
    changed: list[str] = field(default_factory=list)
    done: str = ""
    needs: list[str] = field(default_factory=list)
    doubts: list[str] = field(default_factory=list)

    @classmethod
    def from_structured(cls, data: dict) -> Report:
        done = data.get("done")
        return cls(
            changed=clean_list(data.get("changed")),
            done="" if done is None else str(done).strip(),
            needs=clean_list(data.get("needs")),
            doubts=clean_list(data.get("doubts")),
        )


TEXT_KEY = re.compile(r"^\s*\**(CHANGED|DONE|NEEDS|DOUBTS)\**\s*:\s*(.*)$", re.I)


def parse_text(text: str) -> Report:
    """Report from a plain-text answer (`CHANGED: ...` lines), used when the agent did not
    call the structured tool. `changed` may be comma-separated; each `needs` line is one
    command (commands can contain commas). Without a DONE line, the end of the text is used."""
    raw: dict[str, list[str]] = {"changed": [], "done": [], "needs": [], "doubts": []}
    key = None
    for line in text.splitlines():
        if match := TEXT_KEY.match(line):
            key, value = match.group(1).lower(), match.group(2).strip()
        elif key:
            value = line.strip()
        else:
            continue
        if not value:
            continue
        if key == "changed":
            raw[key] += [x.strip(" -`") for x in value.split(",") if x.strip(" -`")]
        elif key == "needs":
            if command := re.sub(r"^[-*]\s+", "", value).strip():
                raw[key].append(command)
        else:
            raw[key].append(value)
    return Report(
        changed=clean_list(raw["changed"]),
        done=" ".join(raw["done"]) or text.strip()[-300:],
        needs=clean_list(raw["needs"]),
        doubts=clean_list([" ".join(raw["doubts"])]),
    )
