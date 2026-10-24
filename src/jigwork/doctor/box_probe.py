"""Live escape probes for the check box (port of tests/legacy/security_probes.sh, part 3).

A small Python script runs inside the real box and reports what it could reach. `jigw doctor`
runs it with the user's real HOME (a secret file under ~/.cache/jigwork/doctor/ must stay
invisible); tests/security runs it with a fake HOME and, for each probe, a box with exactly
that protection removed (`transform`), which must then report the leak.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import tempfile
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from jigwork.core.git_guard import protected_paths
from jigwork.sandbox.bwrap import BASE_PATH, BwrapSandbox, run_argv

SCRIPT = r"""
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
r["env_cleared"] = cfg["env_var"] not in os.environ
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
WORKING = ("tool_on_path", "project_writable")
ENV_VAR = "JIGWORK_PROBE_SECRET"


class ProbeError(Exception):
    pass


@dataclass
class Layout:
    home: Path  # what the box hides as HOME
    work: Path  # under home: the fake project, tool dir and secret live here
    host_write: Path  # writable on the host, hidden nowhere: the box must not write it
    tmp_secret: Path  # in /tmp on the host

    @property
    def project(self) -> Path:
        return self.work / "proj"

    @property
    def tool(self) -> Path:
        return self.work / "tool"

    @property
    def secret(self) -> Path:
        return self.work / "secret"


@contextmanager
def layout(home: Path, work: Path) -> Iterator[Layout]:
    """Set up the fake project, tool dir and secrets; everything is removed afterwards."""
    if not os.access("/var/tmp", os.W_OK):
        raise ProbeError("the box probe needs a writable /var/tmp")
    work.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(dir="/var/tmp", prefix="jigwork-probe-") as host_dir,
        tempfile.TemporaryDirectory(dir="/tmp", prefix="jigwork-probe-") as tmp_dir,
    ):
        lay = Layout(home, work, Path(host_dir) / "written-from-box", Path(tmp_dir) / "secret")
        try:
            (lay.project / ".git/hooks").mkdir(parents=True)
            (lay.project / "src").mkdir()
            for name in ("AGENTS.md", ".git/hooks/pre-commit", ".git/config"):
                (lay.project / name).write_text("original")
            (lay.project / "probe.py").write_text(SCRIPT)
            (lay.tool / "bin").mkdir(parents=True)
            (lay.tool / "bin/probe-tool").write_text("#!/bin/sh\n")
            (lay.tool / "bin/probe-tool").chmod(0o755)
            (lay.tool / "lib.py").write_text("original")
            lay.secret.write_text("key")
            lay.tmp_secret.write_text("key")
            yield lay
        finally:
            shutil.rmtree(work, ignore_errors=True)


@contextmanager
def _listener() -> Iterator[int]:
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
    try:
        yield server.getsockname()[1]
    finally:
        stop.set()
        thread.join()
        server.close()


def box_argv(lay: Layout, port: int) -> list[str]:
    config = {
        "home_secret": str(lay.secret),
        "home_write": str(lay.home / "jigwork-written-from-box"),
        "host_write": str(lay.host_write),
        "tmp_secret": str(lay.tmp_secret),
        "port": port,
        "host_pid": os.getpid(),
        "env_var": ENV_VAR,
        "tool_file": str(lay.tool / "lib.py"),
    }
    return BwrapSandbox().command(
        lay.project,
        f"python3 probe.py '{json.dumps(config)}'",
        readonly=protected_paths(lay.project),
        extra_ro_mounts=[lay.tool],
        path_prepend=[lay.tool / "bin"],
        home=lay.home,
    )


def run(
    lay: Layout, transform: Callable[[list[str], Layout], list[str]] | None = None
) -> dict[str, bool]:
    if shutil.which("python3", path=BASE_PATH) is None:
        raise ProbeError("the box probe needs a system python3 in /usr/bin")
    report_file = lay.project / "box-report.json"
    report_file.unlink(missing_ok=True)
    old = os.environ.get(ENV_VAR)
    os.environ[ENV_VAR] = "visible"  # the box must not pass the environment on
    try:
        with _listener() as port:
            argv = box_argv(lay, port)
            if transform is not None:
                argv = transform(argv, lay)
            result = run_argv(argv, timeout=60)
    finally:
        if old is None:
            os.environ.pop(ENV_VAR, None)
        else:
            os.environ[ENV_VAR] = old
    if result.returncode != 0 or not report_file.exists():
        raise ProbeError(
            f"the probe did not run in the box (exit {result.returncode}):\n{result.output[-1500:]}"
        )
    report = json.loads(report_file.read_text())
    leaked_home = lay.home / "jigwork-written-from-box"
    report["home_write_lost"] = not leaked_home.exists()
    leaked_home.unlink(missing_ok=True)
    report["root_readonly"] = report["root_readonly"] and not lay.host_write.exists()
    return report
