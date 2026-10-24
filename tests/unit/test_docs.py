"""The user docs stay in step with the CLI."""

import re

import pytest

from jigwork import cli, completion

from .conftest import ROOT

GUIDES = [
    ROOT / "docs/en/guide.md",
    ROOT / "docs/tr/rehber.md",
    ROOT / "README.md",
    ROOT / "README.tr.md",
]


# for converting projects of the developer's own prototype; not part of the user docs
UNDOCUMENTED = {"migrate"}


def commands():
    out = []
    for name, _, sub in completion._subcommands(cli.build_parser()):
        if name in UNDOCUMENTED:
            continue
        out.append(name)
        out += [f"{name} {child}" for child, _, _ in completion._subcommands(sub)]
    return out


@pytest.mark.parametrize("guide", GUIDES[:2], ids=lambda p: p.name)
def test_every_command_is_in_the_guide(guide):
    text = guide.read_text()
    missing = []
    for command in commands():
        parent, _, child = command.partition(" ")
        if f"jigw {command}" in text:
            continue
        # "jigw server start | stop | status" style lists
        if child and re.search(rf"jigw {parent} [\w|/ ]*\b{child}\b", text):
            continue
        missing.append(command)
    assert missing == []


@pytest.mark.parametrize("guide", GUIDES, ids=lambda p: p.name)
def test_shell_snippets_are_fish(guide):
    blocks = re.findall(r"```fish\n(.*?)```", guide.read_text(), re.S)
    assert blocks
    for block in blocks:
        assert "&&" not in block, "fish uses `; and`"


def test_guides_have_the_same_sections():
    def headings(path):
        return len(re.findall(r"^## ", path.read_text(), re.M))

    assert headings(GUIDES[0]) == headings(GUIDES[1])


@pytest.mark.parametrize("guide", GUIDES, ids=lambda p: p.name)
def test_user_docs_do_not_mention_the_prototype(guide):
    text = guide.read_text().lower()
    for word in ("v0", "qwen-kalip", "kalip", "legacy", "orkestra", ".kalip"):
        assert word not in text, word
