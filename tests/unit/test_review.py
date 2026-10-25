"""Signs of weakened tests (core/review.py), on real git trees."""

import subprocess

import pytest

from jigwork.core import git_guard, review


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_cli.py",
        "tests/helpers.py",
        "pkg/test/data.json",
        "test_model.py",
        "src/model_test.py",
        "conftest.py",
        "tests/unit/x.cpp",
        "src/parse_test.cc",
        "web/app.spec.ts",
        "lib/util.test.js",
    ],
)
def test_test_files(path):
    assert review.is_test_file(path)


@pytest.mark.parametrize(
    "path", ["src/todo/cli.py", "testing.py", "src/latest.py", "docs/tests.md", "contest.py"]
)
def test_not_test_files(path):
    assert not review.is_test_file(path)


def test_counts_python_and_cpp():
    py = (
        "def test_a():\n    assert x\n\n"
        "async def test_b():\n    with pytest.raises(E):\n        f()\n"
    )
    assert review.counts(py) == (2, 2)
    cpp = "TEST(Parse, Empty) {\n  EXPECT_EQ(1, 1);\n  ASSERT_TRUE(ok);\n}\nTEST_F(F, X) {}\n"
    assert review.counts(cpp) == (2, 2)


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)

    def snapshot(files: dict[str, str | None]) -> str:
        for name, text in files.items():
            path = root / name
            if text is None:
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
        return git_guard.worktree_tree(root)

    snapshot.root = root
    return snapshot


TWO = "def test_a():\n    assert a\n\ndef test_b():\n    assert b\n"
ONE = "def test_a():\n    assert a\n"


def keys(found):
    return [(f.key, f.paths) for f in found]


def find(tree, before, after, attempt=2, task_type="code"):
    return review.attempt_findings(tree.root, before, after, attempt, task_type)


def test_fix_that_changes_only_tests(tree):
    before = tree({"src/a.py": "x = 1\n", "tests/test_a.py": TWO})
    after = tree({"tests/test_a.py": TWO.replace("assert b", "assert b or True")})
    assert keys(find(tree, before, after)) == [("only_tests", ("tests/test_a.py",))]


def test_first_attempt_and_test_tasks_may_change_only_tests(tree):
    before = tree({"tests/test_a.py": ONE})
    after = tree({"tests/test_a.py": TWO})
    assert find(tree, before, after, attempt=1) == []
    assert find(tree, before, after, attempt=2, task_type="test") == []


def test_fix_that_changes_code_too_is_fine(tree):
    before = tree({"src/a.py": "x = 1\n", "tests/test_a.py": ONE})
    after = tree({"src/a.py": "x = 2\n", "tests/test_a.py": TWO})
    assert find(tree, before, after) == []


def test_removed_test_and_assertion_is_weakened(tree):
    before = tree({"src/a.py": "x = 1\n", "tests/test_a.py": TWO})
    after = tree({"src/a.py": "x = 2\n", "tests/test_a.py": ONE})
    assert keys(find(tree, before, after, attempt=1)) == [("weakened", ("tests/test_a.py",))]


def test_deleted_test_file_is_weakened(tree):
    before = tree({"src/a.py": "x = 1\n", "tests/test_a.py": ONE})
    after = tree({"src/a.py": "x = 2\n", "tests/test_a.py": None})
    assert keys(find(tree, before, after, attempt=1)) == [("weakened", ("tests/test_a.py",))]


def test_new_test_file_is_not_weakened(tree):
    before = tree({"src/a.py": "x = 1\n"})
    after = tree({"src/a.py": "x = 2\n", "tests/test_a.py": ""})
    assert find(tree, before, after, attempt=1) == []


def test_nothing_changed(tree):
    before = tree({"tests/test_a.py": ONE})
    assert find(tree, before, before) == []


def test_english_notes():
    only = review.Finding("only_tests", 2, ("tests/test_a.py",))
    assert only.english() == "fix attempt 2 changed only tests (tests/test_a.py)"
    weak = review.Finding("weakened", 3, ("a_test.py", "b_test.py"))
    assert weak.english() == "tests lost cases or assertions in attempt 3 (a_test.py, b_test.py)"
