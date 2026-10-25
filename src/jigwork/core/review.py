"""Signs that an accepted task needs a human look (findings #15).

Small models pass failing checks by changing the test instead of the code. Two signs, checked
per agent attempt by comparing the work tree before and after it:

* `only_tests`: a fix attempt changed test files and nothing else (not for `test` tasks).
* `weakened`: a test file lost test cases or assertions (deleted test files count too).

Both are heuristics: they mark a task for review, they never fail it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from jigwork.core.git_guard import GitError, git

TEST_DIRS = {"tests", "test"}
TEST_NAME = re.compile(
    r"^(test_.+|.+_test|conftest)\.(py|c|cc|cpp|cxx|h|hpp)$|^.+\.(test|spec)\.\w+$"
)
CASE = re.compile(r"^\s*(async\s+)?def\s+test\w*\s*\(|\bTEST(_F|_P|_CASE)?\s*\(", re.M)
ASSERTION = re.compile(r"\b(assert\w*|ASSERT_\w+|EXPECT_\w+|REQUIRE\w*|CHECK\w*|raises)\b")


def is_test_file(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return bool(TEST_DIRS & set(parts[:-1])) or bool(TEST_NAME.match(parts[-1]))


def counts(text: str) -> tuple[int, int]:
    """(test cases, assertions) in a test file."""
    return len(CASE.findall(text)), len(ASSERTION.findall(text))


@dataclass(frozen=True)
class Finding:
    key: str  # "only_tests" or "weakened"; i18n message run.review_<key>
    attempt: int
    paths: tuple[str, ...]

    def english(self) -> str:
        """For STATUS.md and the commit body."""
        files = ", ".join(self.paths)
        if self.key == "only_tests":
            return f"fix attempt {self.attempt} changed only tests ({files})"
        return f"tests lost cases or assertions in attempt {self.attempt} ({files})"


def _text(root: Path, tree: str, path: str) -> str | None:
    try:
        return git(root, "show", f"{tree}:{path}")
    except (GitError, UnicodeDecodeError):
        return None  # absent in that tree, or not text


def changed_paths(root: Path, before: str, after: str) -> list[str]:
    if before == after:
        return []
    out = git(root, "diff", "--name-only", "--no-renames", "-z", before, after)
    return [p for p in out.split("\0") if p]


def attempt_findings(
    root: Path, before: str, after: str, attempt: int, task_type: str
) -> list[Finding]:
    """What one agent attempt (work tree `before` -> `after`) did to the tests."""
    changed = changed_paths(root, before, after)
    tests = [p for p in changed if is_test_file(p)]
    found = []
    if attempt > 1 and task_type != "test" and tests and len(tests) == len(changed):
        found.append(Finding("only_tests", attempt, tuple(tests)))
    weakened = []
    for path in tests:
        old = _text(root, before, path)
        if old is None:
            continue  # a new file cannot have lost anything
        new = _text(root, after, path) or ""
        (old_cases, old_asserts), (new_cases, new_asserts) = counts(old), counts(new)
        if new_cases < old_cases or new_asserts < old_asserts:
            weakened.append(path)
    if weakened:
        found.append(Finding("weakened", attempt, tuple(weakened)))
    return found
