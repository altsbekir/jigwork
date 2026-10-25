"""The task loop: attempt -> guard -> auto-fix -> checks -> fix prompt -> commit, or patch+reset.

Port of v0 `orkestra.py`. Progress goes through `say(level, key, **fields)`: `key` names an i18n
message, so this module prints nothing itself. Levels: title, step, info, dim, ok, warn, error,
command. Anything the run writes into the project (STATUS.md, commit messages) is English.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from jigwork.agents.base import Agent
from jigwork.agents.base import Limits as AgentLimits
from jigwork.core import git_guard, review, stats, status, tasks
from jigwork.core.checks import CheckRun, PrepareError, check_tools, only_checks, run_checks
from jigwork.core.project import Project
from jigwork.core.prompts import fix_prompt, load_skills, task_prompt
from jigwork.sandbox.base import Sandbox
from jigwork.servers.metrics import ServerCounters

Say = Callable[..., None]


class Duration(float):
    """Seconds; the renderer shows it as "2m 05s" in the user's language."""


class Stop(Exception):
    """Stop the run for a reason the user must see: `key` is an i18n message."""

    def __init__(self, key: str, **fields: object) -> None:
        super().__init__(key)
        self.key = key
        self.fields = fields


def english_duration(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60}m {seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


class ServerGuard(Protocol):
    """The model server during a run (servers/session.py); None: not watched."""

    def is_up(self) -> bool: ...

    def wait_back(self) -> bool: ...

    def counters(self) -> ServerCounters | None:
        """The server's own token/time totals (servers/metrics.py), None if it has none."""
        ...


NEEDS_USER = 2  # exit code: the agent asked the user to run commands; `jigw resume` continues
SERVER_LOST = 3  # exit code: the model server went away; `jigw resume` continues
RETRIES_PER_ATTEMPT = 2  # automatic repeats of one attempt after the server came back
_RETRY = object()


class Runner:
    def __init__(
        self,
        project: Project,
        agent: Agent,
        sandbox: Sandbox,
        say: Say,
        server: ServerGuard | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.project = project
        self.agent = agent
        self.sandbox = sandbox
        self.say = say
        self.server = server
        self._clock = clock
        self._review: list[str] = []  # English review notes for the task being executed

    # --- state ----------------------------------------------------------------------------

    @property
    def root(self) -> Path:
        return self.project.root

    @property
    def resume_file(self) -> Path:
        return self.project.work_dir / ("yarim.json" if self.project.legacy else "resume.json")

    def _resume_data(self) -> dict:
        try:
            data = json.loads(self.resume_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def resume_state(self) -> tuple[str, int, str] | None:
        """(task id, attempt, reason): reason "needs" (commands for the user) or "server"."""
        data = self._resume_data()
        task_id = data.get("task", data.get("gorev"))
        attempt = data.get("attempt", data.get("deneme", 1))
        reason = data.get("reason", "needs")
        return (str(task_id), int(attempt), str(reason)) if task_id else None

    def _save_resume(
        self, task_id: str, attempt: int, reason: str = "needs", seconds: float = 0
    ) -> None:
        """`seconds`: the task's working time so far; the resumed run adds its own to it."""
        self.project.work_dir.mkdir(parents=True, exist_ok=True)
        keys = ("gorev", "deneme") if self.project.legacy else ("task", "attempt")
        data = dict(zip(keys, (task_id, attempt), strict=True))
        if reason != "needs":
            data["reason"] = reason
        data["seconds"] = int(seconds)  # extra keys, ignored by v0's orkestra
        if self._review:
            data["review"] = self._review
        self.resume_file.write_text(json.dumps(data))

    def load_tasks(self) -> list[tasks.Task]:
        if not self.project.tasks_path.exists():
            raise Stop("run.no_tasks_file", path=self.project.tasks_path)
        return tasks.load(self.project.tasks_path)

    def _require_ignored_work_dir(self) -> None:
        probe = self.project.work_dir / "log" / "x.jsonl"
        ignored = subprocess.run(
            ["git", "-C", str(self.root), "check-ignore", "-q", "--no-index", str(probe)]
        )
        if ignored.returncode != 0:
            rel = self.project.work_dir.relative_to(self.root)
            raise Stop("run.work_dir_not_ignored", path=f"{rel}/")

    # --- commands -------------------------------------------------------------------------

    def run(self, one: bool = False) -> int:
        if self.resume_state() is not None:
            raise Stop("run.resume_pending", path=self.resume_file.relative_to(self.root))
        dirty = git_guard.changed_files(self.root)
        if dirty:
            raise Stop("run.dirty", files="\n  ".join(dirty[:10]))
        self._require_ignored_work_dir()
        handled = 0
        while True:
            task_list = self.load_tasks()
            head = tasks.first_open(task_list)
            if head is None:
                self.say(
                    "info" if handled == 0 else "ok",
                    "run.nothing_pending" if handled == 0 else "run.all_done",
                )
                return 0
            if head.status != tasks.PENDING:
                # later tasks usually build on this one: stop instead of skipping it silently
                raise Stop("run.blocked", id=head.id, status=head.status)
            _, issues = tasks.lint(self.project.tasks_path.read_text(encoding="utf-8"))
            if any(i.task_id == head.id and i.severity == "error" for i in issues):
                raise Stop("run.task_invalid", id=head.id)
            result = self.execute(head, first_attempt=1, skip_agent=False)
            handled += 1
            if result != 0 or one:
                return result

    def resume(self) -> int:
        state = self.resume_state()
        if state is None:
            raise Stop("run.no_resume")
        task_id, attempt, reason = state
        task = next((t for t in self.load_tasks() if t.id == task_id), None)
        if task is None:
            raise Stop("run.resume_task_gone", id=task_id)
        data = self._resume_data()
        before = data.get("seconds", 0)
        before = before if isinstance(before, int | float) and before >= 0 else 0
        notes = data.get("review", [])
        notes = [str(n) for n in notes] if isinstance(notes, list) else []
        self.resume_file.unlink()
        if reason == "server" and attempt == 1:
            result = self.execute(task, 1, False, seconds_before=before, review_before=notes)
        elif reason == "server":
            # the tree is back at the end of attempt n-1: its checks give the fix prompt again
            result = self.execute(
                task, attempt - 1, True, seconds_before=before, review_before=notes
            )
        else:
            result = self.execute(task, attempt, True, seconds_before=before, review_before=notes)
        return self.run() if result == 0 else result

    def check(self) -> int:
        result = self._checks(self.project.log_dir / "manual-check.txt")
        if not result.passed:
            self.say("info", "run.check_output", output=result.failure)
        return 0 if result.passed else 1

    # --- one task -------------------------------------------------------------------------

    def _skills(self, *task_types: str) -> str:
        skills_dir = self.agent.skills_dir(self.root)
        parts = [
            load_skills(skills_dir, self.project.config.skills.get(kind, [])) for kind in task_types
        ]
        return "\n\n".join(parts).strip()

    def execute(
        self,
        task: tasks.Task,
        first_attempt: int,
        skip_agent: bool,
        seconds_before: float = 0,
        review_before: list[str] | None = None,
    ) -> int:
        """After a resume: `seconds_before` is the time the task already took, `review_before`
        the review notes of its earlier attempts."""
        self._review = list(review_before or [])
        limit = self.project.config.limits.attempts
        self.say("title", "run.task_header", id=task.id, title=task.title, type=task.type)
        start = self._clock() - seconds_before
        checks: CheckRun | None = None
        attempt = first_attempt
        retries = 0
        while attempt <= limit:
            if not skip_agent:
                if checks is None:
                    prompt = task_prompt(task, self.root, self._skills(task.type))
                    self.say("step", "run.agent_working", attempt=attempt, attempts=limit)
                else:
                    changed = git_guard.changed_files(self.root)
                    skills = self._skills("fix", task.type)
                    prompt = fix_prompt(task, self.root, attempt, checks.failure, changed, skills)
                    self.say("step", "run.agent_fixing", attempt=attempt, attempts=limit)
                outcome = self._agent_attempt(task, prompt, attempt, retries)
                if outcome is _RETRY:
                    retries += 1
                    continue  # the same attempt again, from the same starting point
                retries = 0
                if outcome is not None:
                    return outcome(start)
            skip_agent = False
            self.say("step", "run.checking")
            checks = self._checks(self.project.log_dir / f"{task.id}-attempt{attempt}-checks.txt")
            stats.add_checks(
                stats.path_for(self.project.log_dir, task.id, attempt),
                checks.passed,
                checks.summary(),
            )
            if checks.passed:
                return self._done(task, attempt, checks, self._clock() - start)
            attempt += 1
        assert checks is not None
        return self._failed(task, limit, checks.summary(), self._clock() - start)

    def _agent_attempt(self, task: tasks.Task, prompt: str, attempt: int, retries: int):
        """Run the agent once. Returns None to go on to the checks, _RETRY to repeat the
        attempt (the server came back after an outage), or a finisher(start)."""
        if self.server is not None and not self.server.is_up():
            # gone while the checks ran: nothing to undo, the attempt has not started
            if retries < RETRIES_PER_ATTEMPT and self.server.wait_back():
                return _RETRY
            return lambda start: self._server_lost(task, attempt, self._clock() - start)
        config = self.project.config.limits
        limits = AgentLimits(config.agent_wall_time, config.agent_tool_calls)
        log = self.project.log_dir / f"{task.id}-attempt{attempt}.jsonl"
        start_tree = git_guard.worktree_tree(self.root)
        snapshot = git_guard.GitSnapshot(self.root)

        def on_event(event) -> None:
            self.say(
                "dim",
                "run.tool",
                seconds=Duration(event.seconds),
                name=event.name,
                target=event.target,
            )

        counters_before = self.server.counters() if self.server is not None else None
        try:
            result = self.agent.run_task(self.root, prompt, limits, log, on_event)
        except BaseException:
            # Interrupted (Ctrl-C): the user's next step is often `git status`, which would run
            # a planted fsmonitor command. Put .git back first, without running git.
            if snapshot.changed():
                snapshot.restore()
                self.say("error", "run.git_restored_after_interrupt")
            raise
        if snapshot.changed():
            # No git command may run now: it could execute what was planted.
            raise Stop(
                "run.git_tampered", names=", ".join(snapshot.changed()), path=snapshot.git_dir
            )
        restored = git_guard.restore_protected(self.root)
        if restored:
            self.say("warn", "run.protected_restored_agent", paths=", ".join(restored))
        self._record_stats(task, attempt, result, counters_before)

        if not result.ok and (
            result.connection_error or (self.server is not None and not self.server.is_up())
        ):
            # The model server went away: not the task's fault, so the attempt does not count.
            self._undo_attempt(task, attempt, start_tree)
            if (
                self.server is not None
                and retries < RETRIES_PER_ATTEMPT
                and self.server.wait_back()
            ):
                return _RETRY
            return lambda start: self._server_lost(task, attempt, self._clock() - start)
        for finding in review.attempt_findings(
            self.root, start_tree, git_guard.worktree_tree(self.root), attempt, task.type
        ):
            self.say(
                "warn", f"run.review_{finding.key}", attempt=attempt, paths=", ".join(finding.paths)
            )
            self._review.append(finding.english())
        if not result.ok:
            self.say("warn", "run.agent_unfinished", error=result.error)
        self.say("dim", "run.agent_done", seconds=Duration(result.seconds), tools=result.tool_calls)
        report = result.report
        if report.done:
            self.say("info", "run.report", text=report.done)
        doubts = "; ".join(report.doubts)
        if doubts:
            self.say("warn", "run.doubts", text=doubts)
        needs = report.needs
        if needs and all(only_checks(c, check_tools(self.project.config)) for c in needs):
            # e.g. "pytest tests/test_cli.py": the checks below run that anyway
            self.say("warn", "run.needs_only_checks", commands="; ".join(needs))
            needs = []
        if needs:
            return lambda start: self._needs(task, attempt, needs, self._clock() - start)
        changed = git_guard.changed_files(self.root)
        if not changed:
            reason = "the agent changed no files" + (f" (doubts: {doubts})" if doubts else "")
            return lambda start: self._failed(task, attempt, reason, self._clock() - start)
        outside = sorted(set(changed) - set(task.files)) if task.files else []
        if outside:
            self.say("warn", "run.outside_files", paths=", ".join(outside))
        return None

    def _record_stats(self, task, attempt, result, counters_before) -> None:
        server = None
        if counters_before is not None and self.server is not None:
            after = self.server.counters()
            server = after.minus(counters_before) if after is not None else None
        path = stats.path_for(self.project.log_dir, task.id, attempt)
        stats.write(path, stats.record(task.id, attempt, result, server))

    def _checks(self, log_path: Path) -> CheckRun:
        try:
            result = run_checks(
                self.project,
                self.sandbox,
                log_path,
                on_build=lambda deps: self.say(
                    "info", "run.preparing_env", deps=", ".join(["pytest", "ruff", *deps])
                ),
                on_autofix=lambda: self.say("dim", "run.autofix_applied"),
                on_line=lambda line: self.say(
                    "ok" if line.passed else "error",
                    "run.check_passed" if line.passed else "run.check_failed",
                    name=line.name,
                    seconds=Duration(line.seconds),
                    code=line.returncode,
                ),
            )
        except PrepareError as exc:
            raise Stop("run.prepare_failed", error=str(exc)) from exc
        if result.no_checks:
            self.say("warn", "run.no_checks")
        if result.restored:
            self.say("warn", "run.protected_restored_checks", paths=", ".join(result.restored))
        return result

    # --- outcomes -------------------------------------------------------------------------

    def _commit(self, message: str, body: str = "") -> None:
        git_guard.git(self.root, "add", "-A")
        args = ["commit", "-q", "-m", message] + (["-m", body] if body else [])
        done = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True)
        if done.returncode != 0:
            raise Stop("run.commit_failed", error=done.stderr.strip())

    def _done(self, task: tasks.Task, attempt: int, checks: CheckRun, seconds: float) -> int:
        changed = git_guard.changed_files(self.root)
        tasks.set_status(self.project.tasks_path, task.id, tasks.DONE)
        note = f"{english_duration(seconds)}; {checks.summary()}; {', '.join(changed)}"
        body = f"jigwork: checks passed on attempt {attempt} ({english_duration(seconds)})"
        if self._review:
            note += f"; {status.REVIEW_MARK}: " + "; ".join(self._review)
            body += f"\njigwork: {status.REVIEW_MARK}: " + "; ".join(self._review)
        status.append_row(self.project.status_path, task, tasks.DONE, attempt, note)
        self._commit(f"{task.id}: {task.title}", body)
        self.say("ok", "run.task_done", id=task.id, attempt=attempt, seconds=Duration(seconds))
        if self._review:
            self.say("warn", "run.review_mark", id=task.id)
        return 0

    def _failed(self, task: tasks.Task, attempt: int, reason: str, seconds: float) -> int:
        work = self.project.work_dir
        patch = None
        if git_guard.changed_files(self.root):
            work.mkdir(parents=True, exist_ok=True)
            patch = work / f"{task.id}-failed-{datetime.now():%Y%m%d-%H%M%S}.patch"
            git_guard.git(self.root, "add", "-A")
            patch.write_text(
                git_guard.git(self.root, "diff", "--cached", "--binary"), encoding="utf-8"
            )
            git_guard.git(self.root, "reset", "-q", "--hard")
        tasks.set_status(self.project.tasks_path, task.id, tasks.FAILED)
        rel_patch = patch.relative_to(self.root) if patch else None
        note = f"{reason}; " + (f"patch: {rel_patch}" if rel_patch else "no changes")
        status.append_row(self.project.status_path, task, tasks.FAILED, attempt, note)
        self._commit(f"{task.id}: failed ({reason[:60]})")
        self.say("error", "run.task_failed", id=task.id, reason=reason)
        if rel_patch:
            self.say("info", "run.failed_patch", patch=rel_patch)
        self.say("info", "run.failed_hint", logs=self.project.log_dir.relative_to(self.root))
        return 1

    def _undo_attempt(self, task: tasks.Task, attempt: int, start_tree: str) -> None:
        """Save what a cut-off attempt wrote as a patch, then go back to where it started."""
        patch = git_guard.diff_from_tree(self.root, start_tree)
        if not patch:
            return
        self.project.work_dir.mkdir(parents=True, exist_ok=True)
        stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
        path = self.project.work_dir / f"{task.id}-attempt{attempt}-interrupted-{stamp}.patch"
        path.write_text(patch, encoding="utf-8")
        git_guard.restore_tree(self.root, start_tree)
        self.say("warn", "run.attempt_undone", patch=path.relative_to(self.root))

    def _server_lost(self, task: tasks.Task, attempt: int, seconds: float) -> int:
        self._save_resume(task.id, attempt, reason="server", seconds=seconds)
        self.say("error", "run.server_lost", id=task.id, attempt=attempt)
        self.say("info", "run.server_lost_hint", path=self.resume_file.relative_to(self.root))
        return SERVER_LOST

    def _needs(self, task: tasks.Task, attempt: int, commands: list[str], seconds: float) -> int:
        self._save_resume(task.id, attempt, seconds=seconds)
        self.say("warn", "run.needs_intro", id=task.id)
        for command in commands:
            self.say("command", "run.needs_command", command=command)
        self.say("info", "run.needs_hint", path=self.resume_file.relative_to(self.root))
        return NEEDS_USER
