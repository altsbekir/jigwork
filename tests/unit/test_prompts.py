from pathlib import Path

import pytest

from jigwork.core import prompts
from jigwork.core.prompts import fix_prompt, load_skills, task_prompt, trim_output
from jigwork.core.tasks import Task

TASK = Task(
    id="T2",
    title="Load and save",
    line=1,
    files=["src/todo/storage.py", "tests/test_storage.py"],
    task="  Write load(path) and save(path, todos).\nUse todo.model.  ",
    acceptance=["load returns [] for a missing file", "round trip works"],
)


@pytest.fixture
def project(tmp_path):
    (tmp_path / "src/todo").mkdir(parents=True)
    (tmp_path / "src/todo/storage.py").write_text("")
    skills = tmp_path / ".qwen/skills"
    for name, body in {
        "python-code": "---\nname: python-code\ndescription: x\n---\n# Code rules\n- typed\n",
        "python-test": "# Test rules\n- pytest\n",
        "fix-failing-checks": "---\nname: fix\n---\n\nRead the first error.\n",
        "no-skill-file": None,
    }.items():
        (skills / name).mkdir(parents=True)
        if body is not None:
            (skills / name / "SKILL.md").write_text(body)
    return tmp_path


def v0_task(legacy):
    return legacy.Gorev(
        kimlik=TASK.id,
        baslik=TASK.title,
        baslik_satiri=0,
        dosyalar=TASK.files,
        gorev=TASK.task,
        kabul=TASK.acceptance,
    )


@pytest.mark.parametrize(
    "patterns", [["*-code", "*-test"], ["*-test"], [], ["fix-failing-checks", "*"], ["missing"]]
)
def test_skills_match_v0(project, legacy, patterns):
    assert load_skills(project / ".qwen/skills", patterns) == legacy.skill_metni(project, patterns)


def test_skills_missing_dir(tmp_path):
    assert load_skills(tmp_path / "nope", ["*"]) == ""


def test_task_prompt_matches_v0(project, legacy):
    skills = load_skills(project / ".qwen/skills", prompts.DEFAULT_SKILLS["code"])
    assert skills
    assert task_prompt(TASK, project, skills) == legacy.ilk_prompt(v0_task(legacy), project, skills)
    assert task_prompt(TASK, project, "") == legacy.ilk_prompt(v0_task(legacy), project, "")


def test_fix_prompt_matches_v0(project, legacy):
    skills = load_skills(project / ".qwen/skills", ["fix-failing-checks", "*-code"])
    output = "$ pytest -q\nE   assert 1 == 2"
    for changed in (["src/todo/storage.py"], []):
        new = fix_prompt(TASK, project, 2, output, changed, skills)
        old = legacy.duzeltme_promptu(v0_task(legacy), project, 2, output, changed, skills)
        assert new == old


def test_files_are_marked_exists_or_new(project):
    text = task_prompt(TASK, project, "")
    assert "- src/todo/storage.py (exists)\n" in text
    assert "- tests/test_storage.py (new, create it)\n" in text


def test_task_without_files(tmp_path):
    task = Task(id="T1", title="x", line=1, task="do", acceptance=["a"])
    assert "- (not specified; decide from docs/ARCHITECTURE.md)" in task_prompt(task, tmp_path, "")


def test_model_facing_text_is_ascii():
    for text in (prompts.WORK_RULES, prompts.TRIMMED):
        assert text.isascii()
    assert fix_prompt(TASK, Path("/nonexistent"), 2, "", [], "").isascii()


def test_trim_output_short_input_only_drops_blank_lines():
    assert trim_output("a\n\n  \nb\n") == "a\nb"


def test_trim_output_matches_v0_line_limit(legacy):
    output = "\n".join(f"line {i}" for i in range(200))
    assert trim_output(output) == legacy.ozetle(output).replace("(kısaltıldı)", "(trimmed)")


def test_trim_output_limits():
    lines = [f"line {i} " + "x" * 200 for i in range(200)]
    text = trim_output("\n".join(lines))
    assert len(text) <= 6000
    assert text.startswith("line 0 ")
    assert text.endswith(lines[-1])
    assert prompts.TRIMMED in text
