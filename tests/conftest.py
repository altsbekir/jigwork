"""Shared fixtures. Tests never touch the real HOME, ~/.qwen or the model server (AGENTS.md)."""

import pytest

from jigwork import i18n

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
