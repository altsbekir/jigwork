import re
import string
from pathlib import Path

import pytest

import jigwork
from jigwork import i18n, user_config
from jigwork.cli import main

SRC = Path(jigwork.__file__).parent


def placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


# --- catalogs --------------------------------------------------------------------------------


@pytest.mark.parametrize("lang", [lang for lang in i18n.SUPPORTED if lang != i18n.DEFAULT])
def test_catalog_has_same_keys_and_placeholders_as_english(lang):
    en, other = i18n.catalog(i18n.DEFAULT), i18n.catalog(lang)
    assert set(other) == set(en)
    for key, template in en.items():
        assert placeholders(other[key]) == placeholders(template), key


@pytest.mark.parametrize("lang", i18n.SUPPORTED)
def test_catalog_values_are_strings(lang):
    assert all(isinstance(v, str) for v in i18n.catalog(lang).values())


def test_every_key_used_in_code_exists():
    used = set()
    for path in SRC.rglob("*.py"):
        used |= set(re.findall(r"""\bt\(\s*["']([\w.]+)["']""", path.read_text("utf-8")))
    assert used, "the scan found no t() calls; the regex is broken"
    assert used <= set(i18n.catalog(i18n.DEFAULT))


def test_every_supported_language_has_a_name():
    assert set(i18n.NATIVE_NAMES) == set(i18n.SUPPORTED)


def test_unknown_key_raises():
    with pytest.raises(KeyError):
        i18n.t("no.such.key")


# --- selection -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("tr_TR.UTF-8", "tr"),
        ("tr", "tr"),
        ("en_US.utf8", "en"),
        ("TR-tr", "tr"),
        ("tr_TR@euro", "tr"),
        ("de_DE.UTF-8", None),
        ("C", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize(value, expected):
    assert i18n.normalize(value) == expected


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"LANG": "tr_TR.UTF-8"}, "tr"),
        ({"LANG": "en_US.UTF-8"}, "en"),
        ({"LANG": "de_DE.UTF-8"}, None),
        ({"LC_ALL": "en_US.UTF-8", "LANG": "tr_TR.UTF-8"}, "en"),
        ({"LC_MESSAGES": "tr_TR.UTF-8", "LANG": "en_US.UTF-8"}, "tr"),
        ({"LC_ALL": "de_DE.UTF-8", "LANG": "tr_TR.UTF-8"}, None),
        ({"LANGUAGE": "de:tr:en", "LANG": "en_US.UTF-8"}, "tr"),
        ({"LANGUAGE": "tr", "LANG": "C"}, None),  # gettext ignores LANGUAGE under the C locale
        ({"LANGUAGE": "tr", "LC_ALL": "POSIX", "LANG": "en_US.UTF-8"}, None),
        ({"LANGUAGE": "tr"}, None),
        ({}, None),
    ],
)
def test_from_locale(env, expected):
    found = i18n.from_locale(env)
    assert (found[0] if found else None) == expected


def test_default_is_english():
    assert i18n.resolve() == i18n.Selection("en", "default")


def test_locale_is_used(monkeypatch):
    monkeypatch.setenv("LANG", "tr_TR.UTF-8")
    assert i18n.resolve() == i18n.Selection("tr", "locale", "LANG=tr_TR.UTF-8")


def test_saved_setting_beats_locale(monkeypatch):
    monkeypatch.setenv("LANG", "tr_TR.UTF-8")
    user_config.set_value("lang", "en")
    assert i18n.resolve().lang == "en"
    assert i18n.resolve().source == "config"


def test_env_var_beats_saved_setting(monkeypatch):
    user_config.set_value("lang", "en")
    monkeypatch.setenv("JIGWORK_LANG", "tr")
    assert i18n.resolve() == i18n.Selection("tr", "env", "tr")


def test_unsupported_values_are_skipped(monkeypatch):
    monkeypatch.setenv("JIGWORK_LANG", "de")
    user_config.set_value("lang", "fr")
    monkeypatch.setenv("LANG", "tr_TR.UTF-8")
    assert i18n.resolve().lang == "tr"


def test_broken_settings_file_does_not_break_selection(monkeypatch):
    path = user_config.config_path()
    path.parent.mkdir(parents=True)
    path.write_text("lang = [unclosed\n")
    monkeypatch.setenv("LANG", "tr_TR.UTF-8")
    assert i18n.resolve().lang == "tr"


def test_t_uses_active_language(monkeypatch):
    monkeypatch.setenv("JIGWORK_LANG", "tr")
    assert i18n.t("cli.usage") == "kullanım: "


# --- jigw lang -------------------------------------------------------------------------------


def test_lang_shows_default(capsys):
    assert main(["lang"]) == 0
    assert capsys.readouterr().out == "Language: English (default)\n"


def test_lang_set_saves_and_switches(capsys, isolated_home):
    assert main(["lang", "tr"]) == 0
    out = capsys.readouterr().out
    path = isolated_home / ".config" / "jigwork" / "config.toml"
    assert out.startswith("Dil Türkçe olarak ayarlandı.")
    assert str(path) in out
    assert user_config.load(path) == {"lang": "tr"}

    assert main(["lang"]) == 0
    assert capsys.readouterr().out.startswith("Dil: Türkçe (")


def test_lang_auto_removes_setting(capsys, monkeypatch):
    main(["lang", "tr"])
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert main(["lang", "auto"]) == 0
    assert "English" in capsys.readouterr().out
    assert "lang" not in user_config.load()


def test_lang_set_warns_when_env_var_overrides(capsys, monkeypatch):
    monkeypatch.setenv("JIGWORK_LANG", "en")
    assert main(["lang", "tr"]) == 0
    assert "JIGWORK_LANG=en" in capsys.readouterr().out


def test_lang_set_refuses_broken_settings_file(capsys):
    path = user_config.config_path()
    path.parent.mkdir(parents=True)
    path.write_text("lang = [unclosed\n")
    assert main(["lang", "tr"]) == 1
    assert "Cannot read" in capsys.readouterr().err
    assert path.read_text() == "lang = [unclosed\n"


def test_lang_rejects_unknown_language(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["lang", "de"])
    assert exc.value.code == 2
    assert "jigw lang: error:" in capsys.readouterr().err


def test_help_is_translated(capsys, monkeypatch):
    monkeypatch.setenv("JIGWORK_LANG", "tr")
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert out.startswith("kullanım: jigw")
    assert "seçenekler" in out
    assert "bu yardım iletisini göster ve çık" in out
    assert "arayüz dilini göster veya ayarla" in out


def test_error_prefix_is_translated(capsys, monkeypatch):
    monkeypatch.setenv("JIGWORK_LANG", "tr")
    with pytest.raises(SystemExit):
        main(["no-such-command"])
    assert "jigw: hata:" in capsys.readouterr().err
