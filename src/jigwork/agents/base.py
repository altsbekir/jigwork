"""What the core needs from a coding agent (Qwen Code first). See docs/architecture.md."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from jigwork.core.report import Report


@dataclass(frozen=True)
class Limits:
    wall_time: str = "45m"
    max_tool_calls: int = 80


@dataclass(frozen=True)
class Event:
    """Progress from a running agent: one tool call, `target` relative to the project."""

    name: str
    target: str
    seconds: float


@dataclass(frozen=True)
class Call:
    """One model request in an agent session, as the agent reported it."""

    seconds: float  # since the session started, when the answer arrived
    input_tokens: int
    output_tokens: int  # thinking included
    cached_tokens: int = 0


@dataclass
class SessionStats:
    calls: list[Call] = field(default_factory=list)
    retries: int = 0  # requests the agent repeated (Qwen Code: system/retry events)
    report_source: str = ""  # "tool" (structured_output), "text" (plain-text fallback) or ""
    output_tokens: int = 0  # the agent's own total, retried requests included
    input_tokens: int = 0

    @property
    def longest_reply(self) -> int:
        return max((c.output_tokens for c in self.calls), default=0)


@dataclass
class AgentResult:
    ok: bool  # the agent finished and a report was obtained
    report: Report
    error: str = ""  # "limit" (time or tool-call limit hit), "exit:<code>", or the agent's message
    seconds: float = 0.0
    tool_calls: int = 0
    connection_error: bool = False  # the agent could not reach the model server
    stats: SessionStats = field(default_factory=SessionStats)


@dataclass(frozen=True)
class SecurityCheck:
    """One required (or recommended) agent setting; `key` names an i18n message."""

    key: str
    ok: bool
    required: bool = True


class Agent(Protocol):
    name: str

    def required_security(self) -> list[SecurityCheck]: ...

    def skills_dir(self, project: Path) -> Path: ...

    def install_project(
        self, project: Path, skills: list[tuple[str, dict[str, str]]]
    ) -> tuple[list[str], list[str]]: ...

    def model_url(self) -> str | None: ...

    def model_context(self) -> int | None: ...

    def model_name(self) -> str | None: ...

    def run_task(
        self,
        project: Path,
        prompt: str,
        limits: Limits,
        log_path: Path,
        on_event: Callable[[Event], None],
    ) -> AgentResult: ...

    def chat(self, project: Path, args: list[str]) -> int: ...
