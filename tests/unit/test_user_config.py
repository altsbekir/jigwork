import tomllib

import pytest

from jigwork import user_config


def test_path_follows_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert user_config.config_path() == tmp_path / "xdg" / "jigwork" / "config.toml"


def test_path_defaults_to_dot_config(isolated_home):
    assert user_config.config_path() == isolated_home / ".config" / "jigwork" / "config.toml"


def test_missing_file_is_empty():
    assert user_config.load() == {}
    assert user_config.get("lang") is None


def test_set_creates_file():
    path = user_config.set_value("lang", "tr")
    assert path.read_text() == 'lang = "tr"\n'


def test_set_keeps_comments_other_keys_and_tables(tmp_path):
    path = tmp_path / "config.toml"
    original = '# mine\nother = 1\nlang = "en"  # old\n\n[server]\nlang = "keep"\n'
    path.write_text(original)
    user_config.set_value("lang", "tr", path)
    assert path.read_text() == '# mine\nother = 1\nlang = "tr"\n\n[server]\nlang = "keep"\n'


def test_set_inserts_before_first_table(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[server]\nport = 8091")
    user_config.set_value("lang", "tr", path)
    assert tomllib.loads(path.read_text()) == {"lang": "tr", "server": {"port": 8091}}


def test_set_none_removes_key_only(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('lang = "tr"\nother = 1\n')
    user_config.set_value("lang", None, path)
    assert path.read_text() == "other = 1\n"
    user_config.set_value("lang", None, path)  # removing again is a no-op
    assert path.read_text() == "other = 1\n"


def test_value_is_escaped(tmp_path):
    path = tmp_path / "config.toml"
    user_config.set_value("lang", 'a"b\\c\nd', path)
    assert user_config.get("lang", path) == 'a"b\\c\nd'


def test_broken_file_raises_and_is_left_alone(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("lang = [\n")
    with pytest.raises(user_config.ConfigError):
        user_config.get("lang", path)
    with pytest.raises(user_config.ConfigError):
        user_config.set_value("lang", "tr", path)
    assert path.read_text() == "lang = [\n"
