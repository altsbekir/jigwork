from datetime import datetime

import pytest

from jigwork.core.status import HEADER, append_row
from jigwork.core.tasks import Task

TASK = Task(id="T1", title="Parse | lines", line=1)
WHEN = datetime(2026, 10, 24, 9, 5)


def test_new_file_gets_english_header(tmp_path):
    path = tmp_path / "docs/STATUS.md"
    append_row(path, TASK, "done", 2, "1m 05s; pytest passed\nsecond line", when=WHEN)
    assert path.read_text() == HEADER + (
        "| 2026-10-24 09:05 | T1 Parse / lines | done | 2 | 1m 05s; pytest passed second line |\n"
    )


def test_appends_to_existing_file_without_trailing_newline(tmp_path):
    path = tmp_path / "STATUS.md"
    path.write_text("# Status\n\n" + HEADER + "| old | row | done | 1 | x |")
    append_row(path, TASK, "failed", 3, "a|b", when=WHEN)
    lines = path.read_text().splitlines()
    assert lines[-2] == "| old | row | done | 1 | x |"
    assert lines[-1] == "| 2026-10-24 09:05 | T1 Parse / lines | failed | 3 | a/b |"


def test_v0_file_keeps_turkish_results(tmp_path, legacy):
    v0 = "# Status: x\n\n| Tarih | Görev | Sonuç | Deneme | Not |\n|---|---|---|---|---|\n"
    ours, theirs = tmp_path / "ours", tmp_path / "theirs"
    for name in (ours, theirs):
        (name / "docs").mkdir(parents=True)
        (name / "docs/STATUS.md").write_text(v0, encoding="utf-8")
    task = legacy.Gorev(kimlik="T1", baslik="Parse | lines", baslik_satiri=0)
    for result, v0_word in (("done", "tamam"), ("failed", "başarısız")):
        append_row(ours / "docs/STATUS.md", TASK, result, 1, "n|o", when=WHEN)
        legacy.status_satiri(theirs, task, v0_word, 1, "n|o")

    def without_dates(path):
        return [line.split("|", 2)[2] for line in path.read_text("utf-8").splitlines()[4:]]

    assert ours.joinpath("docs/STATUS.md").read_text("utf-8").startswith(v0)
    # v0 did not escape "|" in the title; the rest of each row is identical
    assert [
        r.replace("Parse / lines", "Parse | lines") for r in without_dates(ours / "docs/STATUS.md")
    ] == without_dates(theirs / "docs/STATUS.md")


def test_unknown_result_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        append_row(tmp_path / "S.md", TASK, "skip", 1, "")
