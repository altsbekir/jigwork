"""Per-user settings file (`$XDG_CONFIG_HOME/jigwork/config.toml`, default `~/.config/...`).

tomllib only reads TOML, so writes are line-based and limited to top-level string keys; comments,
other keys and tables are kept as they are.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path

from jigwork import NAME


class ConfigError(Exception):
    def __init__(self, path: Path, error: str) -> None:
        super().__init__(f"{path}: {error}")
        self.path = path
        self.error = error


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / NAME / "config.toml"


def load(path: Path | None = None) -> dict:
    path = path or config_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ConfigError(path, str(exc)) from exc
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(path, str(exc)) from exc


def get(key: str, path: Path | None = None) -> object | None:
    return load(path).get(key)


def set_value(key: str, value: str | None, path: Path | None = None) -> Path:
    """Set a top-level string key, or remove it when value is None."""
    path = path or config_path()
    load(path)  # refuse to edit a file we cannot parse
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except FileNotFoundError:
        lines = []

    key_line = re.compile(rf"^\s*{re.escape(key)}\s*=")
    new_line = None if value is None else f"{key} = {json.dumps(value)}\n"
    first_table = next((i for i, ln in enumerate(lines) if ln.lstrip().startswith("[")), len(lines))
    existing = next((i for i in range(first_table) if key_line.match(lines[i])), None)

    if existing is not None:
        if new_line is None:
            del lines[existing]
        else:
            lines[existing] = new_line
    elif new_line is not None:
        if first_table > 0 and not lines[first_table - 1].endswith("\n"):
            lines[first_table - 1] += "\n"
        lines.insert(first_table, new_line)
    else:
        return path

    text = "".join(lines)
    tomllib.loads(text)  # never write a file we could not read back
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path
