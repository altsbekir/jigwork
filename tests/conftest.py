"""Shared fixtures. Tests never touch the real HOME, ~/.qwen or the model server (AGENTS.md)."""

import os
import urllib.request
from pathlib import Path

import pytest

from jigwork import i18n

FAKE_SYSTEMCTL = Path(__file__).parent / "fake_model" / "fake_systemctl.py"
REAL_SERVER = ":8091"

LANG_VARS = ("JIGWORK_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for var in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(var, raising=False)
    # Messages default to English; tests that need another language set it explicitly.
    for var in LANG_VARS:
        monkeypatch.delenv(var, raising=False)
    i18n.reset()
    yield home
    i18n.reset()


@pytest.fixture(autouse=True)
def fake_systemd(tmp_path, monkeypatch):
    """Every test sees a fake systemctl/journalctl first on PATH; returns its state dir."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    for name in ("systemctl", "journalctl"):
        (bin_dir / name).symlink_to(FAKE_SYSTEMCTL)
    state = tmp_path / "fake-systemd"
    state.mkdir()
    monkeypatch.setenv("FAKE_SYSTEMD_DIR", str(state))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return state


@pytest.fixture(autouse=True)
def no_real_model_server(monkeypatch):
    """Reaching the real model server's port fails the test instead of quietly working."""
    real_urlopen = urllib.request.urlopen

    def guarded(url, *args, **kwargs):
        target = url if isinstance(url, str) else url.full_url
        if REAL_SERVER in target:
            raise AssertionError(f"a test tried to reach the real model server: {target}")
        return real_urlopen(url, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", guarded)
