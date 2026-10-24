"""Shared fixtures. Tests never touch the real HOME, ~/.qwen or the model server (AGENTS.md)."""

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for var in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(var, raising=False)
    return home
