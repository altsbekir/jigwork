"""Escape probes for the bubblewrap check box (jigwork/doctor/box_probe.py).

Each probe runs inside the real box and must report "protected". Every probe also runs in a
box with exactly one protection removed and must then report the leak: that proves the probe
can tell a broken box from a working one (the "unsafe must fail" self-tests). `jigw doctor`
runs the same probes on the user's machine.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import pytest

from jigwork.core.git_guard import protected_paths
from jigwork.doctor import box_probe
from jigwork.doctor.box_probe import PROBES, Layout
from jigwork.sandbox.bwrap import BwrapSandbox, run_argv

if sys.platform != "linux":
    pytest.skip("bubblewrap is Linux only", allow_module_level=True)
if shutil.which("bwrap") is None:
    pytest.fail("bwrap is not installed: the check box cannot be tested", pytrace=False)


@pytest.fixture
def lay(monkeypatch):
    # HOME must not be under /tmp here, or the /tmp tmpfs would hide it and the HOME probes
    # could not tell whether the HOME tmpfs works. /var/tmp is outside every hidden path.
    with tempfile.TemporaryDirectory(dir="/var/tmp", prefix="jigwork-probe-home-") as home:
        monkeypatch.setenv("HOME", home)
        with box_probe.layout(Path(home), Path(home) / "work") as layout:
            yield layout


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
WEAKENED: dict[str, tuple[Callable[[list[str], Layout], list[str]], set[str]]] = {
    "home_hidden": (lambda a, e: drop(a, "--tmpfs", str(e.home)), {"home_hidden"}),
    "home_write_lost": (
        lambda a, e: rw_root(drop(a, "--tmpfs", str(e.home))),
        {"home_hidden", "home_write_lost", "root_readonly"},
    ),
    "root_readonly": (lambda a, e: rw_root(a), {"root_readonly"}),
    "tmp_hidden": (lambda a, e: drop(a, "--tmpfs", "/tmp"), {"tmp_hidden"}),
    "run_hidden": (lambda a, e: drop(a, "--tmpfs", "/run"), {"run_hidden"}),
    "net_closed": (lambda a, e: replace(a, ("--unshare-all",), ALL_BUT["net"]), {"net_closed"}),
    "pid_isolated": (lambda a, e: replace(a, ("--unshare-all",), ALL_BUT["pid"]), {"pid_isolated"}),
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


def test_every_probe_has_a_weakened_box():
    assert set(WEAKENED) == set(PROBES)


def test_box_blocks_every_probe(lay):
    report = box_probe.run(lay)
    assert {p: report[p] for p in PROBES} == dict.fromkeys(PROBES, True)
    assert report["tool_on_path"] and report["project_writable"]
    assert (lay.project / "src/written-by-box.py").read_text() == "tampered"
    for name in ("AGENTS.md", ".git/hooks/pre-commit"):
        assert (lay.project / name).read_text() == "original"


@pytest.mark.parametrize("probe", PROBES)
def test_probe_detects_a_weakened_box(lay, probe):
    if probe == "run_hidden" and not any(Path("/run").iterdir()):
        pytest.skip("/run is empty on this host, nothing to hide")
    weaken, expected = WEAKENED[probe]
    report = box_probe.run(lay, transform=weaken)
    leaks = {p for p in PROBES if not report[p]}
    assert probe in leaks, f"{probe} did not notice the removed protection"
    assert leaks == expected, "removing one protection must not break the others"


def test_planted_symlink_does_not_mount_its_target(lay):
    """A check left `.env.x -> ~/secret`; the next check must not see the secret through it."""
    (lay.project / ".env.x").symlink_to(lay.secret)
    argv = BwrapSandbox().command(
        lay.project, "cat .env.x", readonly=protected_paths(lay.project), home=lay.home
    )
    assert str(lay.secret) not in argv
    result = run_argv(argv, timeout=30)
    assert result.returncode != 0
    assert "key" not in result.output


def test_run_reports_exit_code_output_and_timeout(lay):
    box = BwrapSandbox()
    result = box.run(lay.project, "echo out; echo err >&2; exit 3", timeout=30)
    assert (result.returncode, result.timed_out) == (3, False)
    assert result.output == "out\nerr\n"
    slow = box.run(lay.project, "echo started; sleep 30", timeout=1)
    assert slow.timed_out and slow.returncode == -1
    assert slow.seconds < 10


def test_layout_cleans_up(tmp_path):
    with tempfile.TemporaryDirectory(dir="/var/tmp") as home:
        with box_probe.layout(Path(home), Path(home) / "work") as layout:
            host_dir = layout.host_write.parent
            assert layout.secret.exists()
        assert not (Path(home) / "work").exists()
        assert not host_dir.exists()
        assert os.listdir(home) == []
