"""Run metrics: one JSON file per agent session next to its log, and their sums.

`<task>-attempt<n>.stats.json` in the project's log dir, written after the agent session and
completed with the checks result. What comes from where:

* the agent's stream (any server): wall time, tool calls, tokens per model request, the longest
  single reply, repeated requests, whether the report came from the report tool or plain text;
* the server's own counters (llama.cpp with `--metrics`, servers/metrics.py): exact prompt and
  generation time, hence tokens per second. Absent for other servers.

`jigw bench` (roadmap phase 2, step 5) reads the same files.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

from jigwork.agents.base import AgentResult
from jigwork.servers.metrics import ServerCounters

SUFFIX = ".stats.json"


def path_for(log_dir: Path, task_id: str, attempt: int) -> Path:
    return log_dir / f"{task_id}-attempt{attempt}{SUFFIX}"


def record(task_id: str, attempt: int, result: AgentResult, server: ServerCounters | None) -> dict:
    stats = result.stats
    out = {
        "task": task_id,
        "attempt": attempt,
        "kind": "task" if attempt == 1 else "fix",
        "seconds": round(result.seconds, 1),
        "tool_calls": result.tool_calls,
        "agent_error": result.error,
        "report": stats.report_source,
        "retries": stats.retries,
        "requests": len(stats.calls),
        "input_tokens": stats.input_tokens or sum(c.input_tokens for c in stats.calls),
        "output_tokens": stats.output_tokens or sum(c.output_tokens for c in stats.calls),
        "longest_reply": stats.longest_reply,
        "calls": [asdict(c) for c in stats.calls],
        "server": None,
        "checks": None,
    }
    if server is not None:
        rates = {"generation_rate": server.generation_rate, "prompt_rate": server.prompt_rate}
        out["server"] = {
            **{k: round(v, 3) for k, v in asdict(server).items()},
            **{k: round(v, 2) if v is not None else None for k, v in rates.items()},
        }
    return out


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


def add_checks(path: Path, passed: bool, summary: str) -> None:
    data = load(path)
    if data is not None:
        data["checks"] = {"passed": passed, "summary": summary}
        write(path, data)


def load(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


@dataclass(frozen=True)
class TaskStats:
    task: str
    sessions: int
    seconds: float
    output_tokens: int
    longest_reply: int
    text_reports: int  # sessions whose report came from the plain-text fallback
    retries: int
    generation_rate: float | None  # median over the sessions the server measured


def _int(value: object) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _attempt(data: dict) -> int:
    return _int(data.get("attempt"))


def summarize(log_dir: Path) -> list[TaskStats]:
    """One row per task, in file order of first appearance (T1, T2, ...)."""
    by_task: dict[str, list[dict]] = {}
    for path in sorted(log_dir.glob(f"*{SUFFIX}")) if log_dir.is_dir() else []:
        data = load(path)
        if data is not None and isinstance(data.get("task"), str):
            by_task.setdefault(data["task"], []).append(data)
    rows = []
    for task, sessions in by_task.items():
        sessions.sort(key=_attempt)
        rates = [
            s["server"]["generation_rate"]
            for s in sessions
            if isinstance(s.get("server"), dict)
            and isinstance(s["server"].get("generation_rate"), int | float)
        ]
        rows.append(
            TaskStats(
                task=task,
                sessions=len(sessions),
                seconds=sum(float(s.get("seconds") or 0) for s in sessions),
                output_tokens=sum(_int(s.get("output_tokens")) for s in sessions),
                longest_reply=max(_int(s.get("longest_reply")) for s in sessions),
                text_reports=sum(1 for s in sessions if s.get("report") == "text"),
                retries=sum(_int(s.get("retries")) for s in sessions),
                generation_rate=statistics.median(rates) if rates else None,
            )
        )
    return sorted(rows, key=lambda r: _natural(r.task))


def _natural(task_id: str) -> tuple:
    digits = "".join(c for c in task_id if c.isdigit())
    return (int(digits) if digits else 0, task_id)
