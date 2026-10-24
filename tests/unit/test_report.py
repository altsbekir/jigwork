import json
from pathlib import Path

import pytest

from jigwork.core import report
from jigwork.core.report import Report, clean_list, parse_text

ROOT = Path(__file__).parents[2]

NOTHING = ["none", "None", " NONE ", "yok", "-", "n/a", "NA", "null", "nothing", "no", "", "`none`"]


def test_schema_is_the_v0_schema():
    v0 = json.loads((ROOT / "legacy/qwen-kalip/orkestra/rapor-semasi.json").read_text())
    assert report.SCHEMA == v0
    assert json.loads(report.schema_json()) == v0


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        ["none"],
        "none",
        "[]",
        '["none"]',
        "['none']",
        [" pip install x ", "none", "`ls`"],
        ["a", "-", "b"],
        "a real doubt",
        3,
        *NOTHING,
    ],
)
def test_clean_list_matches_v0(value, legacy):
    assert clean_list(value) == legacy.liste_temizle(value)


@pytest.mark.parametrize("value", NOTHING)
def test_nothing_is_empty(value):
    assert clean_list([value]) == []


def test_from_structured_normalises():
    data = {"changed": ["a.py", "none"], "done": " ok ", "needs": ["none"], "doubts": "none"}
    assert Report.from_structured(data) == Report(changed=["a.py"], done="ok")


def test_from_structured_tolerates_missing_and_odd_fields():
    data = {"changed": "a.py", "needs": "pip install x", "doubts": ["x", "y"], "done": None}
    assert Report.from_structured(data) == Report(
        changed=["a.py"], done="", needs=["pip install x"], doubts=["x", "y"]
    )
    assert Report.from_structured({}) == Report()


TEXT_SAMPLES = [
    "CHANGED: src/a.py, tests/test_a.py\nDONE: Added parse.\nNEEDS: none\nDOUBTS: none\n",
    "**CHANGED**: a.py\n**DONE**: did it\nover two lines\n**NEEDS**: -\n**DOUBTS**: maybe\nmore\n",
    "Some preamble.\nchanged: `a.py`\ndone:\n  it works\nneeds: yok\ndoubts: yok",
    "No keys at all, just an answer that ends here.",
    "CHANGED:\n- a.py\n- b.py\nDONE: x\n",
]


@pytest.mark.parametrize("text", TEXT_SAMPLES)
def test_parse_text_matches_v0(text, legacy):
    old, new = legacy._metin_raporu(text), parse_text(text)
    assert new.changed == clean_list(old["changed"])
    assert new.done == old["done"]
    assert new.needs == clean_list(old["needs"])
    assert new.doubts == clean_list(old["doubts"])


def test_parse_text_keeps_commas_in_commands():
    # v0 split NEEDS on commas, which broke commands like this one into pieces.
    text = "DONE: x\nNEEDS: python -c 'print(1, 2)'\n- pip install a\nDOUBTS: none\n"
    assert parse_text(text).needs == ["python -c 'print(1, 2)'", "pip install a"]


def test_parse_text_needs_none_is_empty():
    assert parse_text("DONE: x\nNEEDS: none\n").needs == []
    assert parse_text('DONE: x\nNEEDS: ["none"]\n').needs == []


def test_parse_text_done_falls_back_to_end_of_text():
    text = "x" * 500
    assert parse_text(text).done == "x" * 300
