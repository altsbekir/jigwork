import copy
import importlib.util
import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from jigwork import i18n
from jigwork.agents.qwen_code import settings
from jigwork.agents.qwen_code.settings import Endpoint, check, install, merge, user_settings
from jigwork.core import git_guard

ROOT = Path(__file__).parents[2]

V0_SETTINGS = ROOT / "legacy/qwen-kalip/ayarlar/qwen-settings.json"


@pytest.fixture(scope="module")
def v0_merge():
    spec = importlib.util.spec_from_file_location(
        "v0_birlestir", ROOT / "legacy/qwen-kalip/ayarlar/birlestir.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.birlestir


def test_settings_are_v0_plus_documented_changes():
    v0 = json.loads(V0_SETTINGS.read_text())
    ours = user_settings()
    # Turkish words that went to the model server became English
    v0["env"]["LLAMA_API_KEY"] = "local"
    v0["modelProviders"]["openai"][0]["name"] = "Qwen3.6 35B-A3B (local llama.cpp)"
    # the v1 project dir is protected like the v0 one
    v0["permissions"]["deny"].insert(2, "Edit(.jigwork/**)")
    assert ours == v0


def test_endpoint_values_are_used():
    ours = user_settings(Endpoint(base_url="http://127.0.0.1:9/v1", model_id="m", context_window=8))
    provider = ours["modelProviders"]["openai"][0]
    assert (provider["id"], provider["baseUrl"], ours["model"]["name"]) == (
        "m",
        "http://127.0.0.1:9/v1",
        "m",
    )
    assert provider["generationConfig"]["contextWindowSize"] == 8


def test_deny_rules_cover_every_protected_path():
    for path in git_guard.PROTECTED:
        assert f"Edit({path}/**)" in settings.DENY or f"Edit({path})" in settings.DENY, path
    for pattern in git_guard.PROTECTED_GLOBS:
        assert f"Edit({pattern})" in settings.DENY


# --- merge -----------------------------------------------------------------------------------

USER = {
    "theme": "dark",
    "env": {"OTHER": "1", "LLAMA_API_KEY": "old"},
    "modelProviders": {
        "openai": [
            {"id": "qwen3.6-35b-a3b", "baseUrl": "http://old/v1"},
            {"id": "cloud", "baseUrl": "https://example.invalid/v1"},
        ]
    },
    "tools": {"disabled": ["web_fetch"], "executionSandbox": {"backend": "landlock"}},
    "permissions": {"deny": ["Edit(secret/**)", "Edit(.git/**)"], "allow": ["Read(**)"]},
    "memory": {"enableManagedAutoMemory": True},
    "model": "not-a-dict",
}


@pytest.mark.parametrize("current", [{}, USER, {"tools": "broken"}, {"permissions": {"deny": "x"}}])
def test_merge_matches_v0(current, v0_merge):
    ours = merge(copy.deepcopy(current), user_settings())
    assert ours == v0_merge(copy.deepcopy(current), user_settings())


def test_merge_keeps_user_settings_and_ours_win():
    merged = merge(copy.deepcopy(USER), user_settings())
    assert merged["theme"] == "dark"
    assert merged["env"] == {"OTHER": "1", "LLAMA_API_KEY": "local"}
    assert [p["id"] for p in merged["modelProviders"]["openai"]] == ["cloud", "qwen3.6-35b-a3b"]
    assert merged["tools"]["disabled"] == ["web_fetch", *settings.DISABLED_TOOLS]
    assert merged["tools"]["executionSandbox"] == settings.EXECUTION_SANDBOX
    assert merged["permissions"]["deny"][:2] == ["Edit(secret/**)", "Edit(.git/**)"]
    assert set(settings.DENY) <= set(merged["permissions"]["deny"])
    assert len(merged["permissions"]["deny"]) == len(set(merged["permissions"]["deny"]))
    assert merged["memory"]["enableManagedAutoMemory"] is False
    assert all(c.ok for c in check(merged))


def test_merge_does_not_share_objects_with_our_template():
    ours = user_settings()
    merged = merge({}, ours)
    merged["tools"]["disabled"].clear()
    assert ours["tools"]["disabled"] == settings.DISABLED_TOOLS


# --- install ---------------------------------------------------------------------------------


def test_install_new_file(isolated_home):
    path = settings.settings_path()
    assert path == isolated_home / ".qwen/settings.json"
    result = install(path)
    assert result.backup is None
    assert json.loads(path.read_text()) == user_settings()


def test_install_backs_up_and_merges(isolated_home):
    path = settings.settings_path()
    path.parent.mkdir()
    original = json.dumps(USER)
    path.write_text(original)
    os.chmod(path, 0o600)
    result = install(path, now=datetime(2026, 10, 24, 9, 30, 0))
    assert result.backup == path.with_name("settings.json.backup-20261024-093000")
    assert result.backup.read_text() == original
    data = json.loads(path.read_text())
    assert data["theme"] == "dark" and all(c.ok for c in check(data))
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert not path.with_name("settings.json.tmp").exists()


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", ""])
def test_install_refuses_unreadable_file(isolated_home, content):
    path = settings.settings_path()
    path.parent.mkdir()
    path.write_text(content)
    with pytest.raises(settings.SettingsError):
        install(path)
    assert path.read_text() == content
    assert list(path.parent.iterdir()) == [path]


# --- verification (and proof that it fails on an unprotected setup) --------------------------


def failing(data):
    return {c.key for c in check(data) if not c.ok}


def test_our_settings_pass():
    assert failing(user_settings()) == set()


def test_v0_installed_settings_lack_the_v1_deny_rule():
    """Why `jigw setup` must run once before `jigw chat`/`jigw run` on a v0 machine."""
    assert failing(json.loads(V0_SETTINGS.read_text())) == {"qwen.deny_rules"}


def weakened():
    for tool in settings.DISABLED_TOOLS:
        data = user_settings()
        data["tools"]["disabled"].remove(tool)
        yield f"tool {tool}", data, "qwen.tools_disabled"
    for key, value in settings.EXECUTION_SANDBOX.items():
        for bad in (None, "open" if value == "closed" else "x"):
            data = user_settings()
            if bad is None:
                del data["tools"]["executionSandbox"][key]
            else:
                data["tools"]["executionSandbox"][key] = bad
            yield f"sandbox {key}={bad}", data, "qwen.execution_sandbox"
    for rule in settings.DENY:
        data = user_settings()
        data["permissions"]["deny"].remove(rule)
        yield f"deny {rule}", data, "qwen.deny_rules"
    for key in settings.MEMORY_OFF:
        data = user_settings()
        data["memory"][key] = True
        yield f"memory {key}", data, "qwen.memory_off"
    data = user_settings()
    data["skills"]["disabledLevels"] = []
    yield "bundled skills", data, "qwen.bundled_skills_off"
    for section in ("tools", "permissions"):
        data = user_settings()
        data[section] = "garbage"
        yield f"{section} garbage", data, None


@pytest.mark.parametrize(
    ("label", "data", "expected"), list(weakened()), ids=lambda x: x if isinstance(x, str) else ""
)
def test_each_missing_protection_is_detected(label, data, expected):
    found = failing(data)
    assert found
    if expected:
        assert found == {expected}


def test_text_mentions_are_not_enough():
    """v0 searched the raw text; a setting that only mentions the names must fail."""
    data = {
        "note": 'executionSandbox "monitor" "run_shell_command" Edit(.git/**) Edit(docs/TASKS.md)'
    }
    assert {c.key for c in check(data) if c.required and not c.ok} == {
        "qwen.tools_disabled",
        "qwen.execution_sandbox",
        "qwen.deny_rules",
    }


def test_every_check_has_a_message():
    for lang in i18n.SUPPORTED:
        for item in check({}):
            assert f"check.{item.key}" in i18n.catalog(lang)


def test_base_url():
    assert settings.base_url(user_settings()) == "http://127.0.0.1:8091/v1"
    two = {
        "model": {"name": "b"},
        "modelProviders": {"openai": [{"id": "a", "baseUrl": "A"}, {"id": "b", "baseUrl": "B"}]},
    }
    assert settings.base_url(two) == "B"
    two["model"]["name"] = "zzz"
    assert settings.base_url(two) == "A"
    assert settings.base_url({}) is None
