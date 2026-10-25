"""Reading `qwen --output-format stream-json` (format: docs/qwen-code-notes.md, "Headless")."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from jigwork.agents.base import AgentResult, Call, Event, SessionStats
from jigwork.core.report import Report, parse_text

LIMIT_EXIT_CODE = 55  # --max-wall-time / --max-tool-calls exceeded
# Verified on 0.26.0 against a closed port: after ~70 s of retries the session ends with
# error_during_execution, "[API Error: Connection error. (cause: connect ECONNREFUSED ...)]".
CONNECTION_ERROR = re.compile(
    r"API Error: (Connection error|.*ECONNREFUSED|.*ECONNRESET|.*socket hang up)", re.I
)


def _count(value: object) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _short(project: Path, target: str) -> str:
    try:
        return str(Path(target).resolve().relative_to(project.resolve()))
    except (ValueError, OSError):
        return target


@dataclass
class StreamReader:
    project: Path
    ok: bool = False
    report: Report = field(default_factory=Report)
    error: str = ""
    tool_calls: int = 0
    last_text: str = ""
    stats: SessionStats = field(default_factory=SessionStats)

    def feed(self, line: str, seconds: float) -> list[Event]:
        """Process one output line; returns the tool calls it announced."""
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return []
        if not isinstance(event, dict):
            return []
        events = []
        if event.get("type") == "assistant":
            self._usage((event.get("message") or {}).get("usage"), seconds)
            for part in (event.get("message") or {}).get("content") or []:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "tool_use":
                    self.tool_calls += 1
                    args = part.get("input") or {}
                    target = args.get("file_path") or args.get("path") or args.get("pattern") or ""
                    if part.get("name") != "structured_output":
                        events.append(
                            Event(str(part.get("name")), _short(self.project, str(target)), seconds)
                        )
                elif part.get("type") == "text" and str(part.get("text", "")).strip():
                    self.last_text = part["text"]
        elif event.get("type") == "system" and event.get("subtype") == "retry":
            self.stats.retries += 1
        elif event.get("type") == "result":
            self._result(event)
        return events

    def _usage(self, usage: object, seconds: float) -> None:
        """Verified on 0.26.0: each request's usage comes on the last assistant message it
        produced (the thinking/text parts before it carry zeros)."""
        if not isinstance(usage, dict) or not _count(usage.get("output_tokens")):
            return
        self.stats.calls.append(
            Call(
                seconds,
                _count(usage.get("input_tokens")),
                _count(usage.get("output_tokens")),
                _count(usage.get("cache_read_input_tokens")),
            )
        )

    def _result(self, event: dict) -> None:
        usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
        self.stats.output_tokens = _count(usage.get("output_tokens"))
        self.stats.input_tokens = _count(usage.get("input_tokens"))
        if isinstance(event.get("structured_result"), dict) and event["structured_result"]:
            self.report, self.ok = Report.from_structured(event["structured_result"]), True
            self.stats.report_source = "tool"
        elif event.get("subtype") == "success":
            self.report, self.ok = parse_text(event.get("result") or self.last_text), True
            self.stats.report_source = "text"
        else:
            self.error = (event.get("error") or {}).get("message") or str(event.get("subtype", ""))
            # The model answered in plain text instead of calling structured_output
            if self.last_text and "structured_output" in self.error:
                self.report, self.ok = parse_text(self.last_text), True
                self.stats.report_source = "text"

    def finish(self, returncode: int, seconds: float) -> AgentResult:
        ok, error = self.ok, self.error
        if returncode == LIMIT_EXIT_CODE:
            ok, error = False, "limit"
        elif not ok and not error:
            error = f"exit:{returncode}"
        lost = not ok and bool(CONNECTION_ERROR.search(self.error))
        return AgentResult(
            ok,
            self.report,
            error,
            seconds,
            self.tool_calls,
            connection_error=lost,
            stats=self.stats,
        )
