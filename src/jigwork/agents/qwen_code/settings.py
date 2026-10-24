"""Qwen Code user settings (`~/.qwen/settings.json`): what we write, how we merge, what we verify.

Every value here was verified on Qwen Code 0.26 (docs/qwen-code-notes.md, docs/findings.md).
The security part lives at user level on purpose: workspace settings cannot override
`tools.executionSandbox`, and list settings merge as a union across scopes.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from jigwork import PROJECT_DIR
from jigwork.agents.base import SecurityCheck

# findings #1: removing run_shell_command is not enough, monitor runs commands too.
DISABLED_TOOLS = ["run_shell_command", "monitor", "agent", "task_stop"]
# findings #4: without it, auto-edit mode writes outside the project.
EXECUTION_SANDBOX = {"backend": "bwrap", "filesystem": "workspace-write", "network": "closed"}
# findings #2, #3: everything in core.git_guard.PROTECTED (tests check the two stay in step).
DENY = [
    "Edit(.git/**)",
    "Edit(.qwen/**)",
    f"Edit({PROJECT_DIR}/**)",
    "Edit(.kalip/**)",
    "Edit(.env*)",
    "Edit(AGENTS.md)",
    "Edit(CLAUDE.md)",
    "Edit(GEMINI.md)",
    "Edit(docs/TASKS.md)",
    "Edit(docs/STATUS.md)",
    "Edit(pyproject.toml)",
]
# findings #8, #9: second model request per turn, sticky notes; half the system prompt.
MEMORY_OFF = {
    "enableManagedAutoMemory": False,
    "enableManagedAutoDream": False,
    "enableAutoSkill": False,
}
API_KEY_VAR = "LLAMA_API_KEY"


@dataclass(frozen=True)
class Endpoint:
    """The model server Qwen Code talks to. Defaults: the proven setup in docs/context.md.

    Profiles (roadmap step 8) will fill this; until then the defaults are the only source.
    """

    base_url: str = "http://127.0.0.1:8091/v1"
    model_id: str = "qwen3.6-35b-a3b"
    display_name: str = "Qwen3.6 35B-A3B (local llama.cpp)"
    context_window: int = 65536  # must match llama-server -c
    sampling: dict = field(
        default_factory=lambda: {
            "temperature": 0.6,
            "top_p": 0.95,
            "top_k": 20,
            "min_p": 0,
            "presence_penalty": 0,
            "max_tokens": 16384,
        }
    )


def user_settings(endpoint: Endpoint | None = None) -> dict:
    endpoint = endpoint or Endpoint()
    return {
        "env": {API_KEY_VAR: "local"},  # any non-empty value
        "modelProviders": {
            "openai": [
                {
                    "id": endpoint.model_id,
                    "name": endpoint.display_name,
                    "envKey": API_KEY_VAR,
                    "baseUrl": endpoint.base_url,
                    # sealed inside the provider entry; samplingParams is sent verbatim
                    "generationConfig": {
                        "timeout": 900000,
                        "streamIdleTimeoutMs": 600000,
                        "maxRetries": 1,
                        "contextWindowSize": endpoint.context_window,
                        "samplingParams": dict(endpoint.sampling),
                    },
                }
            ]
        },
        "security": {"auth": {"selectedType": "openai"}},
        "model": {"name": endpoint.model_id},
        "memory": dict(MEMORY_OFF),
        "skills": {"disabledLevels": ["bundled"]},
        "tools": {"executionSandbox": dict(EXECUTION_SANDBOX), "disabled": list(DISABLED_TOOLS)},
        "permissions": {"deny": list(DENY)},
    }


def merge(current: dict, ours: dict) -> dict:
    """Merge `ours` into `current` in place; our values win, the user's other settings stay.

    Dicts merge recursively. Lists of {"id": ...} objects: entries with our ids are replaced,
    others kept. Lists of strings: union, the user's entries first (they can add rules or
    disabled tools, never lose ours). Anything else: ours replaces theirs.
    """
    for key, value in ours.items():
        old = current.get(key)
        if isinstance(value, dict) and isinstance(old, dict):
            merge(old, value)
        elif (
            isinstance(value, list)
            and isinstance(old, list)
            and all(isinstance(x, dict) and "id" in x for x in value + old)
        ):
            ids = {x["id"] for x in value}
            current[key] = [x for x in old if x["id"] not in ids] + copy.deepcopy(value)
        elif (
            isinstance(value, list)
            and isinstance(old, list)
            and all(isinstance(x, str) for x in value + old)
        ):
            current[key] = old + [x for x in value if x not in old]
        else:
            current[key] = copy.deepcopy(value)
    return current


class SettingsError(Exception):
    def __init__(self, path: Path, error: str) -> None:
        super().__init__(f"{path}: {error}")
        self.path = path
        self.error = error


def settings_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".qwen" / "settings.json"


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise SettingsError(path, str(exc)) from exc
    if not isinstance(data, dict):
        raise SettingsError(path, "not a JSON object")
    return data


@dataclass(frozen=True)
class InstallResult:
    path: Path
    backup: Path | None  # None when there was no file before


def install(
    path: Path, endpoint: Endpoint | None = None, now: datetime | None = None
) -> InstallResult:
    """Write our settings into `path`, merged with what is there; back the old file up first.

    A file that is not valid JSON is left alone (SettingsError): overwriting it would lose
    the user's settings, merging into a guess could lose ours.
    """
    current = load(path)
    backup = None
    if path.exists():
        stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.name}.backup-{stamp}")
        shutil.copy2(path, backup)
    merged = merge(current, user_settings(endpoint))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if backup is not None:
        os.chmod(tmp, os.stat(backup).st_mode & 0o7777)
    tmp.replace(path)
    return InstallResult(path, backup)


def _get(data: dict, *keys: str) -> object:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def check(settings: dict) -> list[SecurityCheck]:
    """Verify settings structurally (v0 only searched the raw text for a few substrings)."""
    disabled = _get(settings, "tools", "disabled")
    disabled = disabled if isinstance(disabled, list) else []
    sandbox = _get(settings, "tools", "executionSandbox")
    sandbox = sandbox if isinstance(sandbox, dict) else {}
    deny = _get(settings, "permissions", "deny")
    deny = deny if isinstance(deny, list) else []
    memory = _get(settings, "memory")
    memory = memory if isinstance(memory, dict) else {}
    levels = _get(settings, "skills", "disabledLevels")
    levels = levels if isinstance(levels, list) else []
    return [
        SecurityCheck("qwen.tools_disabled", all(t in disabled for t in DISABLED_TOOLS)),
        SecurityCheck(
            "qwen.execution_sandbox",
            all(sandbox.get(k) == v for k, v in EXECUTION_SANDBOX.items()),
        ),
        SecurityCheck("qwen.deny_rules", all(rule in deny for rule in DENY)),
        SecurityCheck(
            "qwen.memory_off", all(memory.get(k) is False for k in MEMORY_OFF), required=False
        ),
        SecurityCheck("qwen.bundled_skills_off", "bundled" in levels, required=False),
    ]


def base_url(settings: dict) -> str | None:
    """The base URL of the provider selected in `model.name` (first one if none matches)."""
    providers = _get(settings, "modelProviders", "openai")
    if not isinstance(providers, list) or not providers:
        return None
    name = _get(settings, "model", "name")
    chosen = next((p for p in providers if isinstance(p, dict) and p.get("id") == name), None)
    chosen = chosen or providers[0]
    url = chosen.get("baseUrl") if isinstance(chosen, dict) else None
    return url if isinstance(url, str) else None
