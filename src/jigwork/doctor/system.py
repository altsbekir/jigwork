"""Facts about the machine and the installed tools (port of legacy/tools/system-check.sh).

Read from /proc and /etc where possible; no sudo (v0 asked for it to read RAM speeds) and no
scan of the whole home folder for model files (the profile names the one that matters).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"
QWEN_VERIFIED = "0.26.0"  # the Qwen Code version docs/qwen-code-notes.md was verified on


@dataclass(frozen=True)
class Fact:
    key: str  # i18n message doctor.<key>
    status: str
    fields: dict


def os_name(os_release: Path = Path("/etc/os-release")) -> str:
    try:
        text = os_release.read_text()
    except OSError:
        return "?"
    match = re.search(r'^PRETTY_NAME="?([^"\n]*)"?', text, re.M)
    return match.group(1) if match else "?"


def cpu(cpuinfo: Path = Path("/proc/cpuinfo")) -> tuple[str, int, set[str]]:
    """(model name, logical CPUs, flags)."""
    try:
        text = cpuinfo.read_text()
    except OSError:
        return "?", 0, set()
    model = re.search(r"^model name\s*:\s*(.+)$", text, re.M)
    flags = re.search(r"^flags\s*:\s*(.+)$", text, re.M)
    count = len(re.findall(r"^processor\s*:", text, re.M))
    return (
        (model.group(1).strip() if model else "?"),
        count,
        set(flags.group(1).split()) if flags else set(),
    )


def memory_gib(meminfo: Path = Path("/proc/meminfo")) -> float | None:
    try:
        match = re.search(r"^MemTotal:\s*(\d+) kB", meminfo.read_text(), re.M)
    except OSError:
        return None
    return int(match.group(1)) / 1024 / 1024 if match else None


def _output(argv: list[str], timeout: float = 20) -> str | None:
    if shutil.which(argv[0]) is None:
        return None
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (done.stdout or done.stderr).strip() if done.returncode == 0 else None


def gpus() -> list[dict] | None:
    """NVIDIA GPUs via nvidia-smi; None when it is not installed."""
    out = _output(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.used,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    if out is None:
        return None
    found = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 4:
            found.append(
                {"name": parts[0], "total": parts[1], "used": parts[2], "driver": parts[3]}
            )
    return found


def version(tool: str, *args: str) -> str | None:
    out = _output([tool, *(args or ("--version",))])
    return out.splitlines()[0] if out else None


def facts(home: Path | None = None) -> list[Fact]:
    home = home or Path.home()
    out = [Fact("os", INFO, {"name": os_name()})]
    model, threads, flags = cpu()
    out.append(Fact("cpu", INFO, {"model": model, "threads": threads}))
    out.append(Fact("avx2", OK, {}) if "avx2" in flags else Fact("no_avx2", WARN, {}))
    if (mem := memory_gib()) is not None:
        out.append(Fact("ram", INFO, {"gib": f"{mem:.1f}"}))
    cards = gpus()
    if not cards:
        out.append(Fact("no_gpu", WARN, {}))
    for card in cards or []:
        out.append(Fact("gpu", INFO, card))
    free = shutil.disk_usage(home).free / 1024**3
    out.append(Fact("disk", OK if free >= 10 else WARN, {"gib": f"{free:.0f}", "path": str(home)}))
    for tool, required in (
        ("git", True),
        ("bwrap", True),
        ("qwen", True),
        ("node", False),
        ("python3", False),
    ):
        found = version(tool)
        status = OK if found else (FAIL if required else WARN)
        out.append(Fact("tool", status, {"name": tool, "version": found or "-"}))
    qwen = version("qwen")
    if qwen and QWEN_VERIFIED not in qwen:
        out.append(Fact("qwen_version", WARN, {"found": qwen, "verified": QWEN_VERIFIED}))
    return out
