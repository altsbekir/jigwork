"""Where checks (lint, tests: model-written code) run. See docs/architecture.md, invariant 4."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class RunResult:
    returncode: int  # -1 when the command was killed for running too long
    output: str  # stdout and stderr, interleaved
    timed_out: bool
    seconds: float


class Sandbox(Protocol):
    name: str

    def available(self) -> bool: ...

    def run(
        self,
        project: Path,
        command: str,
        *,
        readonly: Sequence[Path] = (),
        extra_ro_mounts: Sequence[Path] = (),
        path_prepend: Sequence[Path] = (),
        timeout: float,
    ) -> RunResult:
        """Run a shell command with the project as working directory.

        The project is writable except `readonly` (paths inside it); `extra_ro_mounts` (paths
        outside it, e.g. a test venv) are visible read-only; `path_prepend` goes before PATH.
        No network, no view of HOME, /tmp, /run; a clean environment.
        """
        ...
