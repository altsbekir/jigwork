"""Small terminal helpers shared by commands."""

from __future__ import annotations

from collections.abc import Callable

from jigwork.i18n import t


def confirm(question: str, default: bool, read: Callable[[str], str] = input) -> bool:
    hint = t("ui.default_yes") if default else t("ui.default_no")
    try:
        answer = read(f"{question} {hint} ").strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer in t("ui.yes_words").split(",")
