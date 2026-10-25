"""systemd user services: the model server runs as `systemctl --user` unit `llama-qwen`.

The unit name stays the v0 one, so the desktop launcher and existing setups keep working.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

SERVICE = "llama-qwen"


def unit_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def quote(arg: str) -> str:
    """An ExecStart= argument: double-quoted when it contains spaces or special characters."""
    if arg and not any(c in arg for c in " \t\"'\\;$%"):
        return arg
    escaped = arg.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
    return f'"{escaped}"'


def unit_text(description: str, argv: list[str], header: str) -> str:
    lines = [f"# {header}", "[Unit]", f"Description={description}", "", "[Service]"]
    exec_parts = [quote(a) for a in argv]
    lines.append("ExecStart=" + " \\\n    ".join(_wrap(exec_parts)))
    lines.append("Restart=on-failure")
    return "\n".join(lines) + "\n"


def _wrap(parts: list[str], width: int = 90) -> list[str]:
    """Group arguments into lines of about `width` characters; a flag stays with its value."""
    units: list[str] = []
    i = 0
    while i < len(parts):
        if parts[i].startswith("-") and i + 1 < len(parts) and not parts[i + 1].startswith("-"):
            units.append(f"{parts[i]} {parts[i + 1]}")
            i += 2
        else:
            units.append(parts[i])
            i += 1
    out, line = [], ""
    for unit in units:
        if line and len(line) + 1 + len(unit) > width:
            out.append(line)
            line = unit
        else:
            line = f"{line} {unit}" if line else unit
    if line:
        out.append(line)
    return out


class Systemd:
    def __init__(self, service: str = SERVICE, systemctl: str = "systemctl") -> None:
        self.service = service
        self.systemctl = systemctl

    @property
    def unit_path(self) -> Path:
        return unit_dir() / f"{self.service}.service"

    def _ctl(self, *args: str, capture: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run([self.systemctl, "--user", *args], capture_output=capture, text=True)

    def available(self) -> bool:
        return shutil.which(self.systemctl) is not None

    def exists(self) -> bool:
        return self._ctl("cat", self.service).returncode == 0

    def is_active(self) -> bool:
        return self._ctl("is-active", "--quiet", self.service).returncode == 0

    def invocation_id(self) -> str | None:
        """Changes on every start: tells "the run we started" from a later restart by someone."""
        done = self._ctl("show", "--property=InvocationID", "--value", self.service)
        value = done.stdout.strip() if done.returncode == 0 else ""
        return value or None

    def start(self) -> bool:
        return self._ctl("start", self.service).returncode == 0

    def stop(self) -> bool:
        return self._ctl("stop", self.service).returncode == 0

    def restart(self) -> bool:
        return self._ctl("restart", self.service).returncode == 0

    def daemon_reload(self) -> bool:
        return self._ctl("daemon-reload").returncode == 0

    def write_unit(self, text: str, now: datetime | None = None) -> Path | None:
        """Write the unit file; an existing one is backed up first. Returns the backup path."""
        path = self.unit_path
        backup = None
        if path.exists():
            if path.read_text(encoding="utf-8") == text:
                return None
            backup = path.with_name(f"{path.name}.backup-{(now or datetime.now()):%Y%m%d-%H%M%S}")
            shutil.copy2(path, backup)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        return backup

    def logs(self, follow: bool = True, lines: int = 60, journalctl: str = "journalctl") -> int:
        argv = [journalctl, "--user", "-u", self.service, "-n", str(lines)]
        return subprocess.call(argv + (["-f"] if follow else []))
