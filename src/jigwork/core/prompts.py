"""Prompts sent to the agent: the task prompt, the fix prompt and the "how to work" rules.

Everything here goes to the model, so it is English. The wording is the v0 wording that the
real-model bench passed with (docs/bench-results.md); change it only with a new bench run.
"""

from __future__ import annotations

import re
from pathlib import Path

from jigwork.core.tasks import Task

# Skill name patterns per task type, plus "fix" for fix attempts (inlined into the prompt:
# skills do not work under Qwen Code's execution sandbox, docs/findings.md #10).
DEFAULT_SKILLS = {
    "code": ["*-code", "*-test"],
    "test": ["*-test"],
    "docs": [],
    "fix": ["fix-failing-checks"],
}

WORK_RULES = """\
## How to work
1. Read the listed files marked (exists); files marked (new) do not exist yet, do not try to read them.
   Read docs/ARCHITECTURE.md only if you must create a file that is not listed.
2. Make the change. Stay inside the listed files.
   If another file must change, change it only if unavoidable and say so in "doubts".
3. You cannot run code, tests or linters. They run automatically when you finish.
   So re-read every file you changed once and check imports, names, indentation and syntax by eye.
4. If the task needs a shell command (install a package, a migration, a git operation), do not look for a workaround:
   put the exact command in "needs" and finish.
5. Finish by calling the structured_output tool:
   changed: files you created or edited
   done: one or two sentences
   needs: exact shell commands the user must run (empty list if none)
   doubts: anything uncertain, or "none"
"""  # noqa: E501 (verbatim v0 wording)

FRONT_MATTER = re.compile(r"^---\n.*?\n---\n", re.S)


def load_skills(skills_dir: Path, patterns: list[str]) -> str:
    """Bodies of the SKILL.md files in `skills_dir` whose folder matches a pattern, in order."""
    if not skills_dir.is_dir():
        return ""
    chosen: list[Path] = []
    for pattern in patterns:
        for folder in sorted(skills_dir.glob(pattern)):
            if (folder / "SKILL.md").is_file() and folder not in chosen:
                chosen.append(folder)
    parts = []
    for folder in chosen:
        body = FRONT_MATTER.sub("", (folder / "SKILL.md").read_text(encoding="utf-8"), count=1)
        parts.append(f"### Skill: {folder.name}\n{body.strip()}")
    return "\n\n".join(parts)


def task_section(task: Task, project: Path) -> str:
    def mark(name: str) -> str:
        # The model wastes turns reading files that do not exist yet (docs/findings.md #14)
        return "exists" if (project / name).is_file() else "new, create it"

    files = "\n".join(f"- {name} ({mark(name)})" for name in task.files) or (
        "- (not specified; decide from docs/ARCHITECTURE.md)"
    )
    acceptance = "\n".join(f"- {item}" for item in task.acceptance)
    return (
        f"## Task {task.id}: {task.title}\n{task.task.strip()}\n\n"
        f"## Files\n{files}\n\n"
        f"## Acceptance criteria\n{acceptance}\n"
    )


def _conventions(skills: str) -> str:
    return "\n## Conventions to follow\n" + skills + "\n" if skills else ""


def task_prompt(task: Task, project: Path, skills: str) -> str:
    return task_section(task, project) + "\n" + WORK_RULES + _conventions(skills)


def fix_prompt(
    task: Task, project: Path, attempt: int, check_output: str, changed: list[str], skills: str
) -> str:
    changed_list = "\n".join(f"- {name}" for name in changed) or "- (none)"
    return (
        f"# Fix attempt {attempt} for task {task.id}\n"
        "A previous attempt at this task is already on disk, but the automatic checks failed.\n"
        "Read the failing output, open the files it points to, and fix the cause.\n"
        "Import order and code formatting are fixed automatically; do not spend effort on them.\n\n"
        f"## Check output\n```\n{check_output}\n```\n\n"
        f"## Files changed so far\n{changed_list}\n\n"
        + task_section(task, project)
        + "\n"
        + WORK_RULES
        + _conventions(skills)
    )


TRIMMED = "... (trimmed) ..."


def trim_output(output: str, max_lines: int = 80, max_chars: int = 6000) -> str:
    """Shorten check output for the fix prompt: blank lines dropped, head and tail kept."""
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) > max_lines:
        lines = lines[:20] + [TRIMMED] + lines[-(max_lines - 21) :]
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:2000] + f"\n{TRIMMED}\n" + text[-(max_chars - 2100) :]
    return text
