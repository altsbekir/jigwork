"""The task loop with a scripted agent object and a plain (non-isolating) sandbox.

The real agent CLI and the bubblewrap box are covered by tests/integration/test_loop_e2e.py;
here every branch of the loop is exercised quickly.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from jigwork.agents.base import AgentResult, Event
from jigwork.core import project as project_config
from jigwork.core import tasks
from jigwork.core.loop import Runner, Stop
from jigwork.core.report import Report
from jigwork.sandbox.base import RunResult

TASKS = """\
# Tasks

## T1: Write a
status: pending
type: code
files: src/a.py
task: Create src/a.py containing the word good.
acceptance:
- src/a.py contains good

## T2: Write b
status: pending
type: code
files: src/b.py
task: Create src/b.py.
acceptance:
- src/b.py exists
"""

CONFIG = """\
[prepare]
kind = "none"
[checks]
a_is_good = "grep -q good src/a.py"
b_exists = "test ! -e src/b.py.expected || test -f src/b.py"
[limits]
attempts = 3
"""


class PlainSandbox:
    """Runs check commands directly in the project (no isolation; unit tests only)."""

    name = "plain"

    def available(self) -> bool:
        return True

    def run(self, project, command, *, readonly=(), extra_ro_mounts=(), path_prepend=(), timeout):
        start = time.monotonic()
        done = subprocess.run(
            ["bash", "-c", command], cwd=project, capture_output=True, text=True, timeout=timeout
        )
        return RunResult(
            done.returncode, done.stdout + done.stderr, False, time.monotonic() - start
        )


Step = Callable[[Path, str], AgentResult | None]


class ScriptedAgent:
    """Per (task id, attempt): a function(project, prompt) that edits files and may return a
    custom AgentResult (default: ok with a short report)."""

    name = "scripted"

    def __init__(self, script: dict[tuple[str, int], Step]) -> None:
        self.script = script
        self.prompts: list[tuple[str, int, str]] = []

    def required_security(self):
        return []

    def skills_dir(self, project: Path) -> Path:
        return project / ".qwen" / "skills"

    def model_url(self):
        return None

    def run_task(self, project, prompt, limits, log_path, on_event):
        task_id = (
            prompt.split("task ")[1].split()[0]
            if prompt.startswith("# Fix")
            else prompt.split()[2][:-1]
        )
        attempt = int(prompt.split()[3]) if prompt.startswith("# Fix") else 1
        self.prompts.append((task_id, attempt, prompt))
        on_event(Event("write_file", "src/a.py", 0.5))
        step = self.script.get((task_id, attempt))
        result = step(project, prompt) if step else None
        return result or AgentResult(True, Report(done=f"{task_id} attempt {attempt}"), "", 1.0, 1)

    def chat(self, project, args):
        return 0


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


def write(path: str, text: str) -> Step:
    def step(project: Path, prompt: str):
        target = project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    return step


def steps(*fns: Step) -> Step:
    def step(project: Path, prompt: str):
        result = None
        for fn in fns:
            result = fn(project, prompt) or result
        return result

    return step


def report(**fields) -> Step:
    return lambda project, prompt: AgentResult(True, Report(**fields), "", 1.0, 1)


@pytest.fixture
def repo(isolated_home, monkeypatch):
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "t")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "t@example.invalid")
    root = isolated_home / "proj"
    (root / "docs").mkdir(parents=True)
    (root / ".jigwork").mkdir()
    (root / "docs/TASKS.md").write_text(TASKS)
    (root / ".jigwork/config.toml").write_text(CONFIG)
    (root / "AGENTS.md").write_text("rules\n")
    (root / ".gitignore").write_text(".jigwork/work/\n")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def __call__(self, level: str, key: str, **fields) -> None:
        self.events.append((level, key, fields))

    def keys(self) -> list[str]:
        return [key for _, key, _ in self.events]


def runner(root: Path, script: dict) -> tuple[Runner, ScriptedAgent, Recorder]:
    agent = ScriptedAgent(script)
    say = Recorder()
    return Runner(project_config.load(root), agent, PlainSandbox(), say), agent, say


def statuses(root: Path) -> list[str]:
    return [t.status for t in tasks.load(root / "docs/TASKS.md")]


def log(root: Path) -> list[str]:
    return git(root, "log", "--format=%s").splitlines()


GOOD = {("T1", 1): write("src/a.py", "good\n"), ("T2", 1): write("src/b.py", "")}


# --- the happy path and the fix loop ----------------------------------------------------------


def test_all_tasks_done_and_committed(repo):
    run, agent, say = runner(repo, GOOD)
    assert run.run() == 0
    assert statuses(repo) == ["done", "done"]
    assert log(repo) == ["T2: Write b", "T1: Write a", "init"]
    assert "jigwork: checks passed on attempt 1" in git(repo, "log", "-1", "--format=%b", "HEAD~1")
    assert git(repo, "status", "--porcelain") == ""
    rows = (repo / "docs/STATUS.md").read_text().splitlines()
    assert rows[0] == "| Date | Task | Result | Attempts | Note |"
    assert rows[2].split(" | ", 1)[1].startswith("T1 Write a | done | 1 | ")
    assert rows[2].endswith("s; a_is_good passed, b_exists passed; src/a.py |")
    assert say.keys().count("run.task_done") == 2
    assert say.keys()[-1] == "run.all_done"
    assert [(task, attempt) for task, attempt, _ in agent.prompts] == [("T1", 1), ("T2", 1)]
    assert agent.prompts[0][2].startswith("## Task T1: Write a\n")
    assert (repo / ".jigwork/work/log/T1-attempt1-checks.txt").exists()


def test_one_runs_a_single_task(repo):
    run, _, _ = runner(repo, GOOD)
    assert run.run(one=True) == 0
    assert statuses(repo) == ["done", "pending"]


def test_fix_attempt_gets_the_failing_output(repo):
    script = {
        ("T1", 1): write("src/a.py", "bad\n"),
        ("T1", 2): write("src/a.py", "good\n"),
        ("T2", 1): GOOD[("T2", 1)],
    }
    run, agent, say = runner(repo, script)
    assert run.run() == 0
    assert statuses(repo) == ["done", "done"]
    fix = agent.prompts[1][2]
    assert fix.startswith("# Fix attempt 2 for task T1\n")
    assert "$ grep -q good src/a.py" in fix
    assert "## Files changed so far\n- src/a.py\n" in fix
    assert "run.check_failed" in say.keys() and "run.agent_fixing" in say.keys()
    assert "| T1 Write a | done | 2 |" in (repo / "docs/STATUS.md").read_text()


def test_skills_are_inlined_by_task_type(repo):
    for name in ("python-code", "fix-failing-checks", "unused"):
        (repo / ".qwen/skills" / name).mkdir(parents=True)
        (repo / ".qwen/skills" / name / "SKILL.md").write_text(
            f"---\nname: {name}\n---\n{name} body\n"
        )
    (repo / ".jigwork/config.toml").write_text(CONFIG + '[skills]\ncode = ["python-*"]\n')
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "skills")
    script = {("T1", 1): write("src/a.py", "bad"), ("T1", 2): write("src/a.py", "good")}
    run, agent, _ = runner(repo, script)
    run.run(one=True)
    first, fix = agent.prompts[0][2], agent.prompts[1][2]
    assert "### Skill: python-code" in first and "fix-failing-checks" not in first
    assert fix.index("### Skill: fix-failing-checks") < fix.index("### Skill: python-code")
    assert "unused" not in first + fix


# --- failures -------------------------------------------------------------------------------


def test_out_of_attempts_saves_patch_resets_and_blocks(repo):
    script = {("T1", n): write("src/a.py", f"bad {n}\n") for n in (1, 2, 3)}
    run, agent, say = runner(repo, script)
    assert run.run() == 1
    assert len(agent.prompts) == 3
    assert statuses(repo) == ["failed", "pending"]
    assert log(repo)[0] == "T1: failed (a_is_good failed)"
    assert git(repo, "status", "--porcelain") == ""
    assert not (repo / "src/a.py").exists()
    (patch,) = (repo / ".jigwork/work").glob("T1-failed-*.patch")
    assert "+bad 3" in patch.read_text()
    assert "patch: .jigwork/work/T1-failed-" in (repo / "docs/STATUS.md").read_text()
    # T2 must not run while T1 is failed
    run, agent, _ = runner(repo, GOOD)
    with pytest.raises(Stop) as stop:
        run.run()
    assert (stop.value.key, stop.value.fields["id"], stop.value.fields["status"]) == (
        "run.blocked",
        "T1",
        "failed",
    )
    assert agent.prompts == []


def test_skipped_task_lets_the_next_one_run(repo):
    tasks.set_status(repo / "docs/TASKS.md", "T1", "skip")
    git(repo, "commit", "-q", "-am", "skip T1")
    t2 = steps(write("src/b.py", ""), write("src/a.py", "good"))  # the checks cover the project
    run, agent, _ = runner(repo, {("T2", 1): t2})
    assert run.run() == 0
    assert [p[0] for p in agent.prompts] == ["T2"]


def test_no_changes_fails_the_task(repo):
    run, _, say = runner(repo, {("T1", 1): report(done="nothing to do", doubts=["unclear task"])})
    assert run.run() == 1
    assert statuses(repo)[0] == "failed"
    assert log(repo)[0] == "T1: failed (the agent changed no files (doubts: unclear task))"
    assert "no changes" in (repo / "docs/STATUS.md").read_text()
    assert ("warn", "run.doubts", {"text": "unclear task"}) in say.events


def test_unfinished_agent_session_still_runs_the_checks(repo):
    def broken(project, prompt):
        (project / "src").mkdir()
        (project / "src/a.py").write_text("good")
        return AgentResult(False, Report(), "limit", 1.0, 80)

    run, _, say = runner(repo, {("T1", 1): broken})
    assert run.run(one=True) == 0
    assert ("warn", "run.agent_unfinished", {"error": "limit"}) in say.events


def test_files_outside_the_task_are_reported(repo):
    run, _, say = runner(
        repo, {("T1", 1): steps(write("src/a.py", "good"), write("src/extra.py", ""))}
    )
    assert run.run(one=True) == 0
    assert ("warn", "run.outside_files", {"paths": "src/extra.py"}) in say.events


# --- NEEDS and resume -------------------------------------------------------------------------


def test_needs_stops_and_resume_continues(repo):
    script = {
        ("T1", 1): steps(write("src/a.py", "good"), report(needs=["pip install rich"])),
        ("T2", 1): GOOD[("T2", 1)],
    }
    run, agent, say = runner(repo, script)
    assert run.run() == 2
    assert ("command", "run.needs_command", {"command": "pip install rich"}) in say.events
    assert run.resume_state() == ("T1", 1)
    assert (repo / "src/a.py").exists()  # the agent's work stays for the user to see
    with pytest.raises(Stop) as stop:
        run.run()
    assert stop.value.key == "run.resume_pending"
    assert run.resume() == 0
    assert statuses(repo) == ["done", "done"]
    assert [p[0] for p in agent.prompts] == ["T1", "T2"]  # resume ran the checks, not the agent
    assert run.resume_state() is None


def test_resume_after_failing_checks_goes_to_a_fix_attempt(repo):
    script = {
        ("T1", 1): steps(write("src/a.py", "bad"), report(needs=["make thing"])),
        ("T1", 2): write("src/a.py", "good"),
        ("T2", 1): GOOD[("T2", 1)],
    }
    run, agent, _ = runner(repo, script)
    assert run.run(one=True) == 2
    assert run.resume() == 0
    assert [(p[0], p[1]) for p in agent.prompts] == [("T1", 1), ("T1", 2), ("T2", 1)]
    assert agent.prompts[1][2].startswith("# Fix attempt 2 for task T1\n")


def test_resume_without_state(repo):
    run, _, _ = runner(repo, {})
    with pytest.raises(Stop) as stop:
        run.resume()
    assert stop.value.key == "run.no_resume"


def test_resume_task_removed(repo):
    run, _, _ = runner(repo, {})
    run._save_resume("T9", 1)
    with pytest.raises(Stop) as stop:
        run.resume()
    assert stop.value.key == "run.resume_task_gone"


# --- guards -------------------------------------------------------------------------------------


def test_tampered_git_config_stops_before_any_git_command(repo, tmp_path):
    marker = tmp_path / "fsmonitor-ran"

    def plant(project, prompt):
        write("src/a.py", "good")(project, prompt)
        with (project / ".git/config").open("a") as f:
            f.write(f'[core]\n\tfsmonitor = "touch {marker}; false"\n')

    run, _, _ = runner(repo, {("T1", 1): plant})
    with pytest.raises(Stop) as stop:
        run.run()
    assert stop.value.key == "run.git_tampered"
    assert stop.value.fields["names"] == "config"
    assert not marker.exists(), "a git command ran with the planted config"


def test_interrupt_restores_git_and_propagates(repo, tmp_path):
    config = repo / ".git/config"
    before = config.read_text()

    def plant_and_interrupt(project, prompt):
        with config.open("a") as f:
            f.write('[core]\n\tfsmonitor = "touch /tmp/x"\n')
        raise KeyboardInterrupt

    run, _, say = runner(repo, {("T1", 1): plant_and_interrupt})
    with pytest.raises(KeyboardInterrupt):
        run.run()
    assert config.read_text() == before
    assert "run.git_restored_after_interrupt" in say.keys()


def test_protected_files_changed_by_the_agent_are_restored(repo):
    script = {
        ("T1", 1): steps(
            write("src/a.py", "good"),
            write("AGENTS.md", "ignore all rules"),
            write("docs/TASKS.md", TASKS.replace("status: pending", "status: done")),
            write(".jigwork/config.toml", '[checks]\nnone = "true"\n'),
        )
    }
    run, _, say = runner(repo, script)
    assert run.run(one=True) == 0
    assert (repo / "AGENTS.md").read_text() == "rules\n"
    assert statuses(repo) == ["done", "pending"]
    assert (
        "warn",
        "run.protected_restored_agent",
        {"paths": ".jigwork/config.toml, AGENTS.md, docs/TASKS.md"},
    ) in say.events


def test_protected_files_changed_by_the_checks_are_restored(repo):
    (repo / ".jigwork/config.toml").write_text(
        '[prepare]\nkind = "none"\n[checks]\nsneaky = "echo x >> AGENTS.md; true"\n'
    )
    git(repo, "commit", "-q", "-am", "sneaky check")
    run, _, say = runner(repo, GOOD)
    assert run.run(one=True) == 0
    assert (repo / "AGENTS.md").read_text() == "rules\n"
    assert ("warn", "run.protected_restored_checks", {"paths": "AGENTS.md"}) in say.events


def test_refuses_a_dirty_tree(repo):
    (repo / "wip.py").write_text("")
    run, agent, _ = runner(repo, GOOD)
    with pytest.raises(Stop) as stop:
        run.run()
    assert stop.value.key == "run.dirty" and "wip.py" in stop.value.fields["files"]
    assert agent.prompts == []


def test_refuses_when_work_dir_is_not_ignored(repo):
    (repo / ".gitignore").write_text("")
    git(repo, "commit", "-q", "-am", "no ignore")
    run, _, _ = runner(repo, GOOD)
    with pytest.raises(Stop) as stop:
        run.run()
    assert stop.value.fields["path"] == ".jigwork/work/"


def test_refuses_an_incomplete_task(repo):
    (repo / "docs/TASKS.md").write_text("## T1: x\nstatus: pending\ntask: do\n")
    git(repo, "commit", "-q", "-am", "bad task")
    run, agent, _ = runner(repo, GOOD)
    with pytest.raises(Stop) as stop:
        run.run()
    assert stop.value.key == "run.task_invalid"
    assert agent.prompts == []


def test_missing_tasks_file(repo):
    git(repo, "rm", "-q", "docs/TASKS.md")
    git(repo, "commit", "-q", "-m", "rm")
    run, _, _ = runner(repo, GOOD)
    with pytest.raises(Stop) as stop:
        run.run()
    assert stop.value.key == "run.no_tasks_file"


def test_nothing_pending(repo):
    for task_id in ("T1", "T2"):
        tasks.set_status(repo / "docs/TASKS.md", task_id, "done")
    git(repo, "commit", "-q", "-am", "all done")
    run, _, say = runner(repo, GOOD)
    assert run.run() == 0
    assert say.keys() == ["run.nothing_pending"]


def test_commit_failure_is_reported(repo):
    hook = repo / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\necho refusing >&2\nexit 1\n")
    hook.chmod(0o755)
    run, _, _ = runner(repo, GOOD)
    with pytest.raises(Stop) as stop:
        run.run(one=True)
    assert stop.value.key == "run.commit_failed" and "refusing" in stop.value.fields["error"]


# --- checks ---------------------------------------------------------------------------------


def test_no_checks_accepts_on_the_agents_word(repo):
    (repo / ".jigwork/config.toml").write_text('[prepare]\nkind = "none"\n')
    git(repo, "commit", "-q", "-am", "no checks")
    run, _, say = runner(repo, GOOD)
    assert run.run(one=True) == 0
    assert "run.no_checks" in say.keys()
    assert "no checks" in (repo / "docs/STATUS.md").read_text()


def test_autofix_runs_before_the_checks(repo):
    (repo / ".jigwork/config.toml").write_text(
        '[prepare]\nkind = "none"\n[autofix]\ncommand = "sed -i s/bad/good/ src/a.py"\n'
        '[checks]\ngood = "grep -q good src/a.py"\n'
    )
    git(repo, "commit", "-q", "-am", "autofix")
    run, agent, say = runner(repo, {("T1", 1): write("src/a.py", "bad")})
    assert run.run(one=True) == 0
    assert len(agent.prompts) == 1
    assert "run.autofix_applied" in say.keys()


def test_manual_check(repo):
    run, _, say = runner(repo, {})
    assert run.check() == 1
    level, key, fields = say.events[-1]
    assert key == "run.check_output" and "$ grep -q good src/a.py" in fields["output"]
    (repo / "src").mkdir()
    (repo / "src/a.py").write_text("good")
    assert run.check() == 0


def test_only_the_first_failing_check_runs(repo):
    (repo / ".jigwork/config.toml").write_text(
        '[prepare]\nkind = "none"\n[checks]\nfirst = "false"\nsecond = "touch second-ran"\n'
    )
    git(repo, "commit", "-q", "-am", "two checks")
    run, _, _ = runner(repo, {})
    assert run.check() == 1
    assert not (repo / "second-ran").exists()


# --- v0 projects ------------------------------------------------------------------------------

V0_TASKS = TASKS.replace("status: pending", "durum: bekliyor").replace("type: code", "tip: kod")
V0_TASKS = (
    V0_TASKS.replace("files:", "dosyalar:")
    .replace("task:", "gorev:")
    .replace("acceptance:", "kabul:")
)


@pytest.fixture
def v0_repo(repo):
    (repo / ".jigwork/config.toml").unlink()
    (repo / ".jigwork").rmdir()
    (repo / ".kalip").mkdir()
    (repo / ".kalip/kontroller.toml").write_text(
        '[hazirlik]\ntur = "yok"\n[kontroller]\na = "grep -q good src/a.py"\n'
        "[orkestra]\nmax_deneme = 2\n"
    )
    (repo / "docs/TASKS.md").write_text(V0_TASKS)
    (repo / ".gitignore").write_text(".kalip/calisma/\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "v0")
    return repo


def test_v0_project_keeps_its_names(v0_repo):
    script = {
        ("T1", 1): steps(write("src/a.py", "bad"), report(needs=["x"])),
        ("T1", 2): write("src/a.py", "bad"),
    }
    run, agent, _ = runner(v0_repo, script)
    assert run.project.legacy
    assert run.run(one=True) == 2
    assert (v0_repo / ".kalip/calisma/yarim.json").read_text() == '{"gorev": "T1", "deneme": 1}'
    assert run.resume() == 1  # max_deneme = 2 from the v0 config
    text = (v0_repo / "docs/TASKS.md").read_text()
    assert "## T1: Write a\ndurum: basarisiz\n" in text
    assert list((v0_repo / ".kalip/calisma").glob("T1-failed-*.patch"))
    assert len(agent.prompts) == 2
