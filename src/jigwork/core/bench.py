"""Benchmark task sets: fresh projects, repeated runs, one result table (roadmap phase 2).

A set is a folder with `bench.toml`, `docs/ARCHITECTURE.md`, `docs/TASKS.md` and optionally
`seed/` (existing code copied over the template, for sets that change code rather than write
it). Each run gets a new project from the template, so runs cannot influence each other; the
model is sampled (temperature 0.6), so one run says little: the table gives medians and
ranges over the runs.

This module prints nothing; commands/bench.py runs the loop and shows progress.
"""

from __future__ import annotations

import json
import shutil
import statistics
import subprocess
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

from jigwork.core import scaffold, stats, status, tasks
from jigwork.core.project import PROJECT_TYPES

SET_FILE = "bench.toml"


class BenchError(Exception):
    pass


@dataclass(frozen=True)
class BenchSet:
    root: Path
    name: str  # the project (and Python package) name
    project_type: str
    description: str = ""


def load_set(path: Path) -> BenchSet:
    config = path / SET_FILE
    try:
        data = tomllib.loads(config.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BenchError(f"{config}: {exc.strerror or exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise BenchError(f"{config}: {exc}") from exc
    name = str(data.get("name") or path.name)
    project_type = str(data.get("type", ""))
    if project_type not in PROJECT_TYPES:
        raise BenchError(f"{config}: type must be one of {', '.join(PROJECT_TYPES)}")
    if not scaffold.NAME.match(name):
        raise BenchError(f"{config}: name {name!r} is not a valid project name")
    for doc in ("docs/ARCHITECTURE.md", "docs/TASKS.md"):
        if not (path / doc).is_file():
            raise BenchError(f"{path / doc} is missing")
    found, issues = tasks.lint((path / "docs/TASKS.md").read_text(encoding="utf-8"))
    errors = [i for i in issues if i.severity == "error"]
    if not found or errors:
        raise BenchError(f"{path / 'docs/TASKS.md'}: run `jigw tasks lint` on it")
    return BenchSet(path, name, project_type, str(data.get("description", "")))


def make_project(bench_set: BenchSet, dest: Path, install_agent) -> Path:
    """A new project at dest/<name>: template, the set's docs and seed, one commit.
    `install_agent(root, skills)` installs the skills for the agent (Agent.install_project)."""
    root = dest / bench_set.name
    plan = scaffold.plan(root, bench_set.project_type)
    root.mkdir(parents=True)
    scaffold.apply(plan)
    install_agent(root, plan.skills)
    for doc in ("ARCHITECTURE.md", "TASKS.md"):
        shutil.copyfile(bench_set.root / "docs" / doc, root / "docs" / doc)
    if (bench_set.root / "seed").is_dir():
        shutil.copytree(bench_set.root / "seed", root, dirs_exist_ok=True)
    git = ["git", "-C", str(root)]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    done = subprocess.run(
        [*git, "commit", "-q", "-m", f"bench set {bench_set.name}"], capture_output=True, text=True
    )
    if done.returncode != 0:
        raise BenchError(f"git commit failed: {done.stderr.strip()}")
    return root


@dataclass
class TaskResult:
    task: str
    status: str  # done, failed, pending (not reached, or waiting for NEEDS)
    attempts: int
    agent_seconds: float
    output_tokens: int
    longest_reply: int
    generation_rate: float | None
    text_reports: int
    review: bool


@dataclass
class RunResult:
    index: int
    exit_code: int
    seconds: float
    project: str
    tasks: list[TaskResult] = field(default_factory=list)

    @property
    def done(self) -> int:
        return sum(1 for t in self.tasks if t.status == tasks.DONE)


def collect(root: Path, index: int, exit_code: int, seconds: float, work_dir: Path) -> RunResult:
    """What one run left behind: TASKS.md statuses, STATUS.md rows, the stats files."""
    rows = status.latest_rows(root / "docs/STATUS.md")
    by_task = {s.task: s for s in stats.summarize(work_dir / "log")}
    result = RunResult(index, exit_code, round(seconds, 1), str(root))
    for task in tasks.load(root / "docs/TASKS.md"):
        row = rows.get(task.id)
        session = by_task.get(task.id)
        result.tasks.append(
            TaskResult(
                task=task.id,
                status=task.status,
                attempts=row.attempts if row else (session.sessions if session else 0),
                agent_seconds=session.seconds if session else 0.0,
                output_tokens=session.output_tokens if session else 0,
                longest_reply=session.longest_reply if session else 0,
                generation_rate=session.generation_rate if session else None,
                text_reports=session.text_reports if session else 0,
                review=bool(row and status.REVIEW_MARK in row.note),
            )
        )
    return result


def write_results(path: Path, header: dict, runs: list[RunResult]) -> None:
    data = {**header, "runs": [{**asdict(r), "done": r.done} for r in runs]}
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


def _minutes(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60}m {seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


def _spread(values: list[float], fmt) -> str:
    """median (min–max), or the one value when all runs agree."""
    if not values:
        return "-"
    if min(values) == max(values):
        return fmt(values[0])
    return f"{fmt(statistics.median(values))} ({fmt(min(values))}–{fmt(max(values))})"


def summary(header: dict, runs: list[RunResult]) -> str:
    """A Markdown table for docs/bench-results.md (English, like everything in the repo)."""
    lines = [
        f"## {header['date']}: {header['set']}, jigwork {header['jigwork']}",
        f"Model: {header.get('model') or '?'}; agent: {header.get('agent') or '?'}; "
        f"runs: {len(runs)}.",
        "",
        "| Task | Done | Attempts | Agent time | Tokens | Longest reply | tok/s | Text reports "
        "| Review |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    task_ids = [t.task for t in runs[0].tasks] if runs else []
    for task_id in task_ids:
        per_run = [t for r in runs for t in r.tasks if t.task == task_id]
        done = [t for t in per_run if t.status == tasks.DONE]
        ran = [t for t in per_run if t.attempts]
        rates = [t.generation_rate for t in ran if t.generation_rate is not None]
        lines.append(
            f"| {task_id} | {len(done)}/{len(per_run)} "
            f"| {_spread([t.attempts for t in done], lambda v: f'{v:g}')} "
            f"| {_spread([t.agent_seconds for t in ran], _minutes)} "
            f"| {_spread([t.output_tokens for t in ran], lambda v: f'{v:.0f}')} "
            f"| {max((t.longest_reply for t in ran), default=0)} "
            f"| {_spread(rates, lambda v: f'{v:.1f}')} "
            f"| {sum(t.text_reports for t in ran)} "
            f"| {sum(1 for t in done if t.review)} |"
        )
    total_tasks = sum(len(r.tasks) for r in runs)
    lines += [
        "",
        f"Tasks done: {sum(r.done for r in runs)}/{total_tasks}; all tasks done in "
        f"{sum(1 for r in runs if r.tasks and r.done == len(r.tasks))}/{len(runs)} runs. "
        f"Run time: {_spread([r.seconds for r in runs], _minutes)}.",
        "Attempts: of the runs where the task was done. Agent time, tokens (generated, thinking "
        "included) and tok/s (measured by the server): median (min–max) over the runs that "
        "reached the task. Longest reply: the largest single model answer. Text reports: "
        "sessions that reported in plain text instead of the report tool. Review: done but "
        "marked for human review.",
    ]
    return "\n".join(lines) + "\n"
