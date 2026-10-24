"""`jigw run [--one]`, `jigw resume`, `jigw check`, `jigw status`: the task loop commands."""

from __future__ import annotations

from pathlib import Path

from jigwork.agents.qwen_code import QwenCode
from jigwork.commands import common
from jigwork.core import project as project_config
from jigwork.core import tasks
from jigwork.core.loop import NEEDS_USER, Runner, Stop
from jigwork.i18n import t
from jigwork.sandbox.base import Sandbox
from jigwork.sandbox.bwrap import BwrapSandbox
from jigwork.servers.session import Unavailable

STATUS_MARKS = {tasks.DONE: "✔", tasks.FAILED: "✘", tasks.PENDING: "·", tasks.SKIP: "↷"}


def _runner(cwd: Path, agent: QwenCode, sandbox: Sandbox) -> Runner:
    root = common.toplevel(cwd)
    if root is None:
        raise Stop("run.not_git")
    try:
        project = project_config.load(root)
    except project_config.ConfigError as exc:
        raise Stop("run.bad_config", path=exc.path, error=exc.error) from exc
    return Runner(project, agent, sandbox, common.render)


def run(
    command: str,
    one: bool = False,
    cwd: Path | None = None,
    agent: QwenCode | None = None,
    sandbox: Sandbox | None = None,
    probe_fn=None,
) -> int:
    """command: "run", "resume", "check" or "status"."""
    agent = agent or QwenCode()
    sandbox = sandbox or BwrapSandbox()
    try:
        runner = _runner(cwd or Path.cwd(), agent, sandbox)
        if command == "status":
            return _status(runner)
        if not common.sandbox_ready():
            return 1
        if command == "check":
            return runner.check()
        if not common.agent_ready(agent):
            return 1
        # resume often only reruns the checks: open the server when the agent needs it
        session = common.server_session(agent, probe_fn, lazy=command == "resume")
        if session is None:
            return 1
        with session:
            runner.server = session
            code = runner.resume() if command == "resume" else runner.run(one=one)
            if code == NEEDS_USER:
                session.keep_up()  # reloading the model for `jigw resume` costs minutes
            return code
    except Unavailable as unavailable:
        common.render("error", unavailable.key, **unavailable.fields)
        return 1
    except Stop as stop:
        common.render("error", stop.key, **stop.fields)
        return 1
    except KeyboardInterrupt:
        print()
        common.render("warn", "run.interrupted")
        return 130


def _status(runner: Runner) -> int:
    task_list = runner.load_tasks()
    if not task_list:
        common.render("info", "run.no_tasks")
        return 0
    _, issues = tasks.lint(runner.project.tasks_path.read_text(encoding="utf-8"))
    for task in task_list:
        problems = [
            t(f"tasks.lint.{i.code}", **i.fields)
            for i in issues
            if i.task_id == task.id and i.severity == "error"
        ]
        mark = STATUS_MARKS.get(task.status, "?")
        line = f" {mark} {task.id:<4} {task.status:<8} {task.type:<5} {task.title}"
        if problems and task.status == tasks.PENDING:
            line += "  ← " + "; ".join(problems)
        print(line)
    if (state := runner.resume_state()) is not None:
        common.render("warn", "run.resume_note", id=state[0])
    return 0
