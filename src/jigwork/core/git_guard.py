"""Git as the safety net, and guarding git itself.

Two separate protections (docs/findings.md #2, #3):

* `GitSnapshot`: `.git/config` and `.git/hooks` can make git run commands on the host, outside
  every sandbox. Take a snapshot before an agent run and compare after it. On a mismatch run NO
  git command (it could execute the planted command); stop, or restore from the snapshot.
* `restore_protected`: control files in the work tree (agent settings, AGENTS.md, TASKS.md, ...)
  are put back after an agent run or a check run. It runs git, so check the snapshot first.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from jigwork import PROJECT_DIR

# Paths the agent must not write and checks must not change, relative to the project root.
# `.kalip` is the v0 project dir, kept until `jigw migrate` has converted every project.
PROTECTED = (
    ".git",
    ".qwen",
    PROJECT_DIR,
    ".kalip",
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "docs/TASKS.md",
    "docs/STATUS.md",
    "pyproject.toml",
)
PROTECTED_GLOBS = (".env*",)
# jigwork's own output (logs, patches, resume state) lives under these and may change.
WORK_DIRS = (f"{PROJECT_DIR}/work", ".kalip/calisma")


class GitError(Exception):
    pass


def git(project: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def changed_files(project: Path) -> list[str]:
    """Paths with uncommitted changes, untracked files included, one entry per file."""
    parts = git(project, "status", "--porcelain", "-uall", "-z").split("\0")
    files = []
    i = 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if not entry:
            continue
        code, path = entry[:2], entry[3:]
        files.append(path)
        if "R" in code or "C" in code:
            i += 1  # a rename or copy is followed by its source path
    return files


def worktree_signature(project: Path) -> str:
    """Hash of every uncommitted file: tells whether a step (e.g. auto-fix) changed anything."""
    digest = hashlib.sha256()
    for name in sorted(changed_files(project)):
        digest.update(name.encode())
        path = project / name
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def is_protected(path: str) -> bool:
    if any(path == w or path.startswith(w + "/") for w in WORK_DIRS):
        return False
    if any(path == p or path.startswith(p + "/") for p in PROTECTED):
        return True
    return any(fnmatch.fnmatchcase(path, g) for g in PROTECTED_GLOBS)


def protected_paths(project: Path) -> list[Path]:
    """Existing protected paths of `project`, for read-only mounts in the check box."""
    found = [project / p for p in PROTECTED if (project / p).exists()]
    for pattern in PROTECTED_GLOBS:
        found += sorted(p for p in project.glob(pattern) if p not in found)
    return found


def restore_protected(project: Path) -> list[str]:
    """Undo changes to protected paths: tracked files are checked out, new ones deleted.

    Returns the paths that were restored. Call only after `GitSnapshot.unchanged()`.
    """
    touched = [p for p in changed_files(project) if is_protected(p)]
    for path in touched:
        tracked = (
            subprocess.run(
                ["git", "-C", str(project), "ls-files", "--error-unmatch", "--", path],
                capture_output=True,
            ).returncode
            == 0
        )
        if tracked:
            git(project, "checkout", "--", path)
        else:
            (project / path).unlink(missing_ok=True)
    return touched


@dataclass(frozen=True)
class _Entry:
    mode: int
    data: bytes  # file contents, or the target of a symlink


def git_dir(project: Path) -> Path:
    return Path(git(project, "rev-parse", "--absolute-git-dir").strip())


def _guarded(gitdir: Path) -> list[Path]:
    """Files through which git can run commands: config, per-worktree config and every hook."""
    paths = [gitdir / "config", gitdir / "config.worktree"]
    hooks = gitdir / "hooks"
    paths.append(hooks)
    if hooks.is_dir() and not hooks.is_symlink():
        # os.walk does not follow symlinked directories (Path.rglob did before Python 3.13)
        for root, dirs, files in os.walk(hooks):
            paths += [Path(root, name) for name in sorted(dirs + files)]
    return paths


def _read(gitdir: Path) -> dict[str, _Entry]:
    entries = {}
    for path in _guarded(gitdir):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        name = str(path.relative_to(gitdir))
        if stat.S_ISLNK(info.st_mode):
            entries[name] = _Entry(info.st_mode, os.readlink(path).encode())
        elif stat.S_ISREG(info.st_mode):
            entries[name] = _Entry(info.st_mode, path.read_bytes())
        elif stat.S_ISDIR(info.st_mode):
            entries[name] = _Entry(info.st_mode, b"")
    return entries


class GitSnapshot:
    """`.git/config` and hooks at one point in time (taken without running git afterwards)."""

    def __init__(self, project: Path) -> None:
        self.git_dir = git_dir(project)
        self._entries = _read(self.git_dir)

    def changed(self) -> list[str]:
        """Names (relative to the git dir) added, removed or modified since the snapshot."""
        now = _read(self.git_dir)
        names = set(now) | set(self._entries)
        return sorted(n for n in names if now.get(n) != self._entries.get(n))

    def unchanged(self) -> bool:
        return not self.changed()

    def restore(self) -> None:
        """Put config and hooks back exactly as they were (contents, modes, symlinks)."""
        hooks = self.git_dir / "hooks"
        if hooks.is_symlink() or hooks.is_file():
            hooks.unlink()
        elif hooks.is_dir():
            for root, dirs, files in os.walk(hooks, topdown=False):
                for name in files:
                    Path(root, name).unlink()
                for name in dirs:
                    path = Path(root, name)
                    if path.is_symlink():
                        path.unlink()
                    else:
                        path.rmdir()
            hooks.rmdir()
        for name in ("config", "config.worktree"):
            path = self.git_dir / name
            if (path.is_symlink() or path.exists()) and name not in self._entries:
                path.unlink()
        for name, entry in sorted(self._entries.items()):
            path = self.git_dir / name
            if stat.S_ISDIR(entry.mode):
                path.mkdir(parents=True, exist_ok=True)
                os.chmod(path, stat.S_IMODE(entry.mode))
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_symlink() or path.exists():
                path.unlink()
            if stat.S_ISLNK(entry.mode):
                os.symlink(entry.data.decode(), path)
            else:
                path.write_bytes(entry.data)
                os.chmod(path, stat.S_IMODE(entry.mode))
