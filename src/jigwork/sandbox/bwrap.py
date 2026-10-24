"""Linux check box with bubblewrap (docs/findings.md #5).

Root file system read-only; tmpfs over /tmp, /run (the D-Bus session socket there could ask
systemd to start processes outside the box), /mnt, /media and HOME; the project bind-mounted
writable with control files read-only on top; all namespaces unshared (no network, own PIDs);
environment cleared.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

from jigwork.sandbox.base import RunResult

HIDDEN = ("/tmp", "/run", "/mnt", "/media")
BASE_PATH = "/usr/local/bin:/usr/bin:/bin"


def _too_broad(project: Path, home: Path) -> bool:
    """A project at /, at HOME or above HOME would bind the hidden home back in, writable."""
    return project == Path("/") or project == home or home.is_relative_to(project)


def _inside(path: Path, *roots: Path) -> Path | None:
    for root in roots:
        if path.is_relative_to(root):
            return path.relative_to(root)
    return None


class BwrapSandbox:
    name = "bwrap"

    def available(self) -> bool:
        return shutil.which("bwrap") is not None

    def command(
        self,
        project: Path,
        command: str,
        *,
        readonly: Sequence[Path] = (),
        extra_ro_mounts: Sequence[Path] = (),
        path_prepend: Sequence[Path] = (),
        home: Path | None = None,
    ) -> list[str]:
        home = home or Path.home()
        given, project = project.absolute(), project.resolve()
        if _too_broad(project, home.resolve()):
            raise ValueError(f"refusing to run checks with {project} as the project")
        protected = []
        for path in readonly:
            rel = _inside(Path(path).absolute(), given, project)
            if rel is None or ".." in rel.parts:
                raise ValueError(f"read-only path {path} is not inside {given}")
            target = project / rel
            # Never follow a symlink: one planted by an earlier check (`.env.x -> ~/.ssh/key`)
            # would mount the real file into the box. Restoring protected paths deletes it.
            if any(
                (project / Path(*rel.parts[:i])).is_symlink() for i in range(1, len(rel.parts) + 1)
            ):
                continue
            if target.exists():
                protected.append(target)

        args = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc"]
        for hidden in (*HIDDEN, str(home)):
            if Path(hidden).is_dir():
                args += ["--tmpfs", hidden]
        args += ["--bind", str(project), str(project)]
        for path in protected:
            args += ["--ro-bind", str(path), str(path)]
        for path in extra_ro_mounts:
            args += ["--ro-bind", str(path), str(path)]
        search_path = ":".join([*(str(p) for p in path_prepend), BASE_PATH])
        args += [
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--clearenv",
            "--setenv", "PATH", search_path,
            "--setenv", "HOME", str(home),
            "--setenv", "LANG", "C.UTF-8",
            "--setenv", "TERM", "dumb",
            "--setenv", "NO_COLOR", "1",
            "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
            "--chdir", str(project),
            "--", "bash", "-c", command,
        ]  # fmt: skip
        return args

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
        argv = self.command(
            project,
            command,
            readonly=readonly,
            extra_ro_mounts=extra_ro_mounts,
            path_prepend=path_prepend,
        )
        return run_argv(argv, timeout)


def run_argv(argv: list[str], timeout: float) -> RunResult:
    start = time.monotonic()
    try:
        done = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or b""
        output = partial.decode(errors="replace") if isinstance(partial, bytes) else partial
        return RunResult(-1, output, True, time.monotonic() - start)
    output = done.stdout.decode(errors="replace")
    return RunResult(done.returncode, output, False, time.monotonic() - start)
