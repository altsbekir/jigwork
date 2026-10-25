"""`jigw bench SET [--repeat N] [--out DIR]`: run a task set N times on fresh projects.

Uses the real agent, the real sandbox and the user's model server (opened once for all runs).
Never part of the automatic tests; the tests drive `run_set` with a scripted agent.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from jigwork import __version__
from jigwork.agents.qwen_code import QwenCode
from jigwork.commands import common
from jigwork.core import bench
from jigwork.core import project as project_config
from jigwork.core.checks import cache_dir
from jigwork.core.loop import SERVER_LOST, Runner, Stop
from jigwork.i18n import t
from jigwork.sandbox.base import Sandbox
from jigwork.sandbox.bwrap import BwrapSandbox
from jigwork.servers.session import Unavailable


def run(
    set_path: str,
    repeat: int = 1,
    out: str | None = None,
    agent: QwenCode | None = None,
    sandbox: Sandbox | None = None,
    probe_fn=None,
) -> int:
    agent = agent or QwenCode()
    sandbox = sandbox or BwrapSandbox()
    try:
        bench_set = bench.load_set(Path(set_path).expanduser().absolute())
    except bench.BenchError as exc:
        common.err(t("bench.bad_set", error=exc))
        return 1
    if repeat < 1:
        common.err(t("bench.bad_repeat"))
        return 1
    if not common.sandbox_ready() or not common.agent_ready(agent):
        return 1
    session = common.server_session(agent, probe_fn)
    if session is None:
        return 1
    try:
        with session:
            return run_set(bench_set, repeat, _out_dir(bench_set, out), agent, sandbox, session)
    except Unavailable as unavailable:
        common.render("error", unavailable.key, **unavailable.fields)
        return 1


def _out_dir(bench_set: bench.BenchSet, out: str | None) -> Path:
    if out:
        return Path(out).expanduser().absolute()
    return cache_dir() / "bench" / f"{bench_set.name}-{datetime.now():%Y%m%d-%H%M%S}"


def _agent_name() -> str:
    from jigwork.doctor.system import version

    found = version("qwen")
    return f"Qwen Code {found}" if found else "Qwen Code"


def run_set(
    bench_set: bench.BenchSet, repeat: int, out_dir: Path, agent, sandbox: Sandbox, server
) -> int:
    """The runs, one after another; results are written after every run, so an interrupted
    bench keeps what it measured. 0: all runs completed (whatever the tasks did)."""
    if out_dir.exists() and any(out_dir.iterdir()):
        common.err(t("bench.out_not_empty", path=out_dir))
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    header = {
        "date": f"{datetime.now():%Y-%m-%d}",
        "set": bench_set.name,
        "set_path": str(bench_set.root),
        "jigwork": __version__,
        "model": agent.model_name(),
        "agent": _agent_name() if isinstance(agent, QwenCode) else getattr(agent, "name", ""),
        "repeat": repeat,
    }
    runs: list[bench.RunResult] = []
    code = 0
    common.render("title", "bench.start", set=bench_set.name, repeat=repeat, path=out_dir)
    try:
        for index in range(1, repeat + 1):
            common.render("title", "bench.run_start", index=index, repeat=repeat)
            root = bench.make_project(bench_set, out_dir / f"run-{index}", agent.install_project)
            project = project_config.load(root)
            runner = Runner(project, agent, sandbox, common.render, server=server)
            start = time.monotonic()
            try:
                exit_code = runner.run()
            except Stop as stop:
                common.render("error", stop.key, **stop.fields)
                exit_code = 1
            result = bench.collect(
                root, index, exit_code, time.monotonic() - start, project.work_dir
            )
            runs.append(result)
            _save(out_dir, header, runs)
            common.render(
                "ok" if result.done == len(result.tasks) else "warn",
                "bench.run_done",
                index=index,
                done=result.done,
                total=len(result.tasks),
                seconds=common.Duration(result.seconds),
            )
            if exit_code == SERVER_LOST:
                common.render("error", "bench.server_lost")
                code = 1
                break
    except KeyboardInterrupt:
        print()
        common.render("warn", "bench.interrupted")
        code = 130
    if runs:
        print()
        print(bench.summary(header, runs), end="")
        common.render("info", "bench.saved", path=out_dir)
    return code


def _save(out_dir: Path, header: dict, runs: list[bench.RunResult]) -> None:
    bench.write_results(out_dir / "results.json", header, runs)
    (out_dir / "summary.md").write_text(bench.summary(header, runs), encoding="utf-8")
