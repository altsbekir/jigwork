"""User-facing message catalogs (en, tr) and language selection.

Order: JIGWORK_LANG, then the language saved with `jigw lang`, then the system locale, then
English. Code, prompts and everything sent to the model stay English; only CLI output uses this.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from functools import cache
from importlib import resources

from jigwork import user_config

SUPPORTED = ("en", "tr")
DEFAULT = "en"
NATIVE_NAMES = {"en": "English", "tr": "Türkçe"}
ENV_VAR = "JIGWORK_LANG"
CONFIG_KEY = "lang"


@dataclass(frozen=True)
class Selection:
    lang: str
    source: str  # "env", "config", "locale" or "default"
    detail: str = ""  # env value, config path or "VAR=value" of the locale


def normalize(value: str | None) -> str | None:
    """'tr_TR.UTF-8' -> 'tr'; unsupported or empty -> None."""
    if not value:
        return None
    code = value.split(".")[0].split("@")[0].replace("-", "_").split("_")[0].lower()
    return code if code in SUPPORTED else None


def from_locale(env: dict[str, str] | None = None) -> tuple[str, str] | None:
    """Language from the locale variables, following gettext rules.

    The first non-empty of LC_ALL, LC_MESSAGES, LANG is the locale. "C"/"POSIX" means no
    language (LANGUAGE is ignored then, as gettext does); otherwise LANGUAGE, a colon list of
    preferences, wins over the locale itself.
    """
    env = os.environ if env is None else env
    locale_var = next((v for v in ("LC_ALL", "LC_MESSAGES", "LANG") if env.get(v)), None)
    if locale_var is None or env[locale_var].split(".")[0] in ("C", "POSIX"):
        return None
    for part in env.get("LANGUAGE", "").split(":"):
        if lang := normalize(part):
            return lang, f"LANGUAGE={env['LANGUAGE']}"
    if lang := normalize(env[locale_var]):
        return lang, f"{locale_var}={env[locale_var]}"
    return None


def resolve() -> Selection:
    if lang := normalize(os.environ.get(ENV_VAR)):
        return Selection(lang, "env", os.environ[ENV_VAR])
    try:
        saved = user_config.get(CONFIG_KEY)
    except user_config.ConfigError:
        saved = None  # a broken settings file must not make every command fail
    if isinstance(saved, str) and (lang := normalize(saved)):
        return Selection(lang, "config", str(user_config.config_path()))
    if found := from_locale():
        return Selection(found[0], "locale", found[1])
    return Selection(DEFAULT, "default")


_active: Selection | None = None


def active() -> Selection:
    global _active
    if _active is None:
        _active = resolve()
    return _active


def reset() -> None:
    """Forget the cached selection (after `jigw lang`, and between tests)."""
    global _active
    _active = None


@cache
def catalog(lang: str) -> dict[str, str]:
    data = tomllib.loads(resources.files(__name__).joinpath(f"{lang}.toml").read_text("utf-8"))
    return dict(_flatten(data))


def _flatten(data: dict, prefix: str = ""):
    for key, value in data.items():
        if isinstance(value, dict):
            yield from _flatten(value, f"{prefix}{key}.")
        else:
            yield f"{prefix}{key}", value


def t(key: str, **fields: object) -> str:
    """Message `key` in the active language; falls back to English, KeyError if unknown."""
    template = catalog(active().lang).get(key)
    if template is None:
        template = catalog(DEFAULT)[key]
    return template.format(**fields)
