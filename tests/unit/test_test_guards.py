"""Tests of the test setup itself: no test may touch the real services or model server."""

import shutil
import subprocess
import urllib.request

import pytest

from jigwork.platform.systemd import Systemd
from jigwork.servers.health import is_healthy


def test_systemctl_on_path_is_the_fake(fake_systemd):
    assert "fake-bin" in shutil.which("systemctl")
    assert "fake-bin" in shutil.which("journalctl")
    service = Systemd()
    assert not service.exists()
    assert not service.start()  # the fake service does not exist, so nothing can start
    (fake_systemd / "exists").touch()
    assert service.start() and service.is_active()
    assert "systemctl --user start llama-qwen" in (fake_systemd / "calls.log").read_text()


def test_real_model_server_port_is_blocked():
    with pytest.raises(AssertionError, match="real model server"):
        is_healthy("http://127.0.0.1:8091/v1")
    with pytest.raises(AssertionError):
        urllib.request.urlopen("http://127.0.0.1:8091/health")


def test_subprocesses_see_the_fake_too():
    done = subprocess.run(["systemctl", "--user", "is-active", "llama-qwen"])
    assert done.returncode == 3  # the fake says inactive; the real one is never asked
