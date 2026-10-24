"""Escape probes for the bubblewrap check box (ported from tests/legacy/security_probes.sh, 3.).

Each probe runs inside the real box and must report "protected". Every probe also runs in a
box with exactly one protection removed and must then report the leak: that proves the probe
can tell a broken box from a working one (the "unsafe must fail" self-tests).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from jigwork.core.git_guard import protected_paths
from jigwork.sandbox.bwrap import BwrapSandbox, run_argv

if sys.platform != "linux":
    pytest.skip("bubblewrap is Linux only", allow_module_level=True)
if shutil.which("bwrap") is None:
    pytest.fail("bwrap is not installed: the check box cannot be tested", pytrace=False)
if shutil.which("python3", path="/usr/local/bin:/usr/bin:/bin") is None:
    pytest.fail("the probes need a system python3 in /usr/bin", pytrace=False)

PROBE = r"""
import json, os, pathlib, shutil, socket, sys
cfg = json.loads(sys.argv[1])
r = {}

def readable(path):
    try:
        pathlib.Path(path).read_text(); return True
    except OSError:
        return False

def writable(path):
    try:
        pathlib.Path(path).write_text("tampered"); return True
    except OSError:
        return False

r["home_hidden"] = not readable(cfg["home_secret"])
writable(cfg["home_write"])            # HOME is a tmpfs inside: the write must not reach the host
r["home_write_lost"] = True            # decided on the host side
r["root_readonly"] = not writable(cfg["host_write"])  # a host path that is not hidden
r["tmp_hidden"] = not readable(cfg["tmp_secret"])
r["run_hidden"] = not any(pathlib.Path("/run").iterdir())
try:
    socket.create_connection(("127.0.0.1", cfg["port"]), timeout=2).close()
    r["net_closed"] = False
except OSError:
    r["net_closed"] = True
r["pid_isolated"] = not pathlib.Path(f"/proc/{cfg['host_pid']}").exists()
r["env_cleared"] = "JIGWORK_PROBE_SECRET" not in os.environ
r["git_readonly"] = not writable(".git/hooks/pre-commit")
r["protected_readonly"] = not writable("AGENTS.md")
r["tool_readonly"] = not writable(cfg["tool_file"])
r["tool_on_path"] = shutil.which("probe-tool") is not None
r["project_writable"] = writable("src/written-by-box.py")
pathlib.Path("box-report.json").write_text(json.dumps(r))
"""

PROBES = (
    "home_hidden",
    "home_write_lost",
    "root_readonly",
    "tmp_hidden",
    "run_hidden",
    "net_closed",
    "pid_isolated",
    "env_cleared",
    "git_readonly",
    "protected_readonly",
    "tool_readonly",
)


class Env:
    def __init__(self, home: Path, tmp_root: Path) -> None:
        self.home = home
        self.project = home / "proj"
        self.tool = home / ".cache" / "jigwork" / "venv" / "proj-1234"
        (self.project / ".git" / "hooks").mkdir(parents=True)
        (self.project / "src").mkdir()
        for name in ("AGENTS.md", ".git/hooks/pre-commit", ".git/config"):
            (self.project / name).write_text("original")
        (self.home / "secret").mkdir()
        (self.home / "secret" / "id").write_text("key")
        (self.tool / "bin").mkdir(parents=True)
        (self.tool / "bin" / "probe-tool").write_text("#!/bin/sh\n")
        (self.tool / "bin" / "probe-tool").chmod(0o755)
        (self.tool / "lib.py").write_text("original")
        self.host_write = home.parent / f"{home.name}-written-from-box"
        self.tmp_secret = tmp_root / "tmp-secret"
        self.tmp_secret.write_text("key")
        (self.project / "probe.py").write_text(PROBE)

    def config(self, port: int) -> dict:
        return {
            "home_secret": str(self.home / "secret" / "id"),
            "home_write": str(self.home / "written-from-box"),
            "host_write": str(self.host_write),
            "tmp_secret": str(self.tmp_secret),
            "port": port,
            "host_pid": os.getpid(),
            "tool_file": str(self.tool / "lib.py"),
        }


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("JIGWORK_PROBE_SECRET", "visible")
    # HOME must not be under /tmp here, or the /tmp tmpfs would hide it and the HOME probes
    # could not tell whether the HOME tmpfs works. /var/tmp is outside every hidden path.
    if not os.access("/var/tmp", os.W_OK):
        pytest.fail("the probes need a writable /var/tmp for a fake HOME", pytrace=False)
    with (
        tempfile.TemporaryDirectory(dir="/var/tmp", prefix="jigwork-probe-home-") as home,
        tempfile.TemporaryDirectory(dir="/tmp", prefix="jigwork-probe-") as tmp_root,
    ):
        monkeypatch.setenv("HOME", home)
        env = Env(Path(home), Path(tmp_root))
        try:
            yield env
        finally:
            env.host_write.unlink(missing_ok=True)


@pytest.fixture
def listener():
    """A TCP server on the host's loopback: reachable from the box only if it shares the network."""
    server = socket.create_server(("127.0.0.1", 0))
    server.settimeout(0.2)
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            try:
                server.accept()[0].close()
            except OSError:
                pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield server.getsockname()[1]
    stop.set()
    thread.join()
    server.close()


def box_argv(env: Env, port: int) -> list[str]:
    return BwrapSandbox().command(
        env.project,
        f"python3 probe.py '{json.dumps(env.config(port))}'",
        readonly=protected_paths(env.project),
        extra_ro_mounts=[env.tool],
        path_prepend=[env.tool / "bin"],
    )


def run_probe(env: Env, argv: list[str]) -> dict[str, bool]:
    report_file = env.project / "box-report.json"
    report_file.unlink(missing_ok=True)
    result = run_argv(argv, timeout=60)
    assert result.returncode == 0, result.output
    report = json.loads(report_file.read_text())
    report["home_write_lost"] = not (env.home / "written-from-box").exists()
    report["root_readonly"] = report["root_readonly"] and not env.host_write.exists()
    return report


def drop(argv: list[str], *option: str) -> list[str]:
    """argv without one occurrence of the consecutive items `option`."""
    n = len(option)
    for i in range(len(argv) - n + 1):
        if tuple(argv[i : i + n]) == option:
            return argv[:i] + argv[i + n :]
    raise AssertionError(f"{option} not in the box command")


def replace(argv: list[str], old: tuple[str, ...], new: list[str]) -> list[str]:
    i = next(i for i in range(len(argv)) if tuple(argv[i : i + len(old)]) == old)
    return argv[:i] + new + argv[i + len(old) :]


ALL_BUT = {
    ns: [
        f"--unshare-{n}" for n in ("user-try", "ipc", "pid", "net", "uts", "cgroup-try") if n != ns
    ]
    for ns in ("net", "pid")
}


def rw_root(argv: list[str]) -> list[str]:
    return replace(argv, ("--ro-bind", "/", "/"), ["--bind", "/", "/"])


# probe -> (the box with that protection removed, the probes expected to report a leak).
# Writes to HOME are stopped by two layers (read-only root, tmpfs over HOME): remove both.
WEAKENED: dict[str, tuple[Callable[[list[str], Env], list[str]], set[str]]] = {
    "home_hidden": (lambda a, e: drop(a, "--tmpfs", str(e.home)), {"home_hidden"}),
    "home_write_lost": (
        lambda a, e: rw_root(drop(a, "--tmpfs", str(e.home))),
        {"home_hidden", "home_write_lost", "root_readonly"},
    ),
    "root_readonly": (lambda a, e: rw_root(a), {"root_readonly"}),
    "tmp_hidden": (lambda a, e: drop(a, "--tmpfs", "/tmp"), {"tmp_hidden"}),
    "run_hidden": (lambda a, e: drop(a, "--tmpfs", "/run"), {"run_hidden"}),
    "net_closed": (lambda a, e: replace(a, ("--unshare-all",), ALL_BUT["net"]), {"net_closed"}),
    "pid_isolated": (
        lambda a, e: replace(a, ("--unshare-all",), ALL_BUT["pid"]),
        {"pid_isolated"},
    ),
    "env_cleared": (lambda a, e: drop(a, "--clearenv"), {"env_cleared"}),
    "git_readonly": (
        lambda a, e: drop(a, "--ro-bind", *[str(e.project / ".git")] * 2),
        {"git_readonly"},
    ),
    "protected_readonly": (
        lambda a, e: drop(a, "--ro-bind", *[str(e.project / "AGENTS.md")] * 2),
        {"protected_readonly"},
    ),
    "tool_readonly": (
        lambda a, e: replace(a, ("--ro-bind", str(e.tool)), ["--bind", str(e.tool)]),
        {"tool_readonly"},
    ),
}


def test_box_blocks_every_probe(env, listener):
    report = run_probe(env, box_argv(env, listener))
    assert {p: report[p] for p in PROBES} == dict.fromkeys(PROBES, True)
    assert report["tool_on_path"]
    assert report["project_writable"]
    assert (env.project / "src" / "written-by-box.py").read_text() == "tampered"
    for name in ("AGENTS.md", ".git/hooks/pre-commit"):
        assert (env.project / name).read_text() == "original"


@pytest.mark.parametrize("probe", PROBES)
def test_probe_detects_a_weakened_box(env, listener, probe):
    if probe == "run_hidden" and not any(Path("/run").iterdir()):
        pytest.skip("/run is empty on this host, nothing to hide")
    weaken, expected = WEAKENED[probe]
    report = run_probe(env, weaken(box_argv(env, listener), env))
    leaks = {p for p in PROBES if not report[p]}
    assert probe in leaks, f"{probe} did not notice the removed protection"
    assert leaks == expected, "removing one protection must not break the others"


def test_planted_symlink_does_not_mount_its_target(env, listener):
    """A check left `.env.x -> ~/secret/id`; the next check must not see the secret through it."""
    (env.project / ".env.x").symlink_to(env.home / "secret" / "id")
    argv = box_argv(env, listener)
    assert str(env.home / "secret" / "id") not in argv
    result = run_argv(
        BwrapSandbox().command(env.project, "cat .env.x", readonly=protected_paths(env.project)),
        timeout=30,
    )
    assert result.returncode != 0
    assert "key" not in result.output


def test_run_reports_exit_code_output_and_timeout(env):
    box = BwrapSandbox()
    result = box.run(env.project, "echo out; echo err >&2; exit 3", timeout=30)
    assert (result.returncode, result.timed_out) == (3, False)
    assert result.output == "out\nerr\n"
    slow = box.run(env.project, "echo started; sleep 30", timeout=1)
    assert slow.timed_out and slow.returncode == -1
    assert slow.seconds < 10
