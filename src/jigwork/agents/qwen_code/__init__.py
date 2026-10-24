"""Qwen Code adapter: settings, security verification, headless task runs, interactive chat."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from jigwork.agents.base import AgentResult, Event, Limits, SecurityCheck
from jigwork.agents.qwen_code import settings
from jigwork.agents.qwen_code.stream import StreamReader
from jigwork.core import report

YOLO_ARGS = ("-y", "--yolo", "--approval-mode=yolo", "yolo")


class QwenCode:
    name = "qwen-code"

    def __init__(self, executable: str = "qwen", home: Path | None = None) -> None:
        self.executable = executable
        self.home = home

    def available(self) -> bool:
        return shutil.which(self.executable) is not None

    def settings(self) -> dict:
        return settings.load(settings.settings_path(self.home))

    def required_security(self) -> list[SecurityCheck]:
        return settings.check(self.settings())

    def run_task(
        self,
        project: Path,
        prompt: str,
        limits: Limits,
        log_path: Path,
        on_event: Callable[[Event], None],
    ) -> AgentResult:
        """One fresh headless session. Guarding .git and protected files is the caller's job
        (core), so it holds for every agent."""
        log_path.parent.mkdir(parents=True, exist_ok=True)
        schema = log_path.parent / "report-schema.json"
        schema.write_text(report.schema_json(), encoding="utf-8")
        argv = [
            self.executable,
            prompt,
            "--approval-mode", "auto-edit",
            "--output-format", "stream-json",
            "--json-schema", f"@{schema}",
            "--max-wall-time", limits.wall_time,
            "--max-tool-calls", str(limits.max_tool_calls),
        ]  # fmt: skip
        reader = StreamReader(project)
        start = time.monotonic()
        with open(log_path, "w", encoding="utf-8") as log:
            log.write(json.dumps({"prompt": prompt}, ensure_ascii=False) + "\n")
            process = subprocess.Popen(
                argv,
                cwd=project,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                start_new_session=True,
            )
            try:
                assert process.stdout is not None
                for line in process.stdout:
                    log.write(line)
                    for event in reader.feed(line, time.monotonic() - start):
                        on_event(event)
                process.wait()
            except BaseException:  # Ctrl-C included: never leave the agent running
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                process.wait()
                raise
        return reader.finish(process.returncode, time.monotonic() - start)

    def chat(self, project: Path, args: list[str]) -> int:
        """Interactive session in the terminal. Callers check `refused_args` first."""
        return subprocess.call([self.executable, *args], cwd=project)

    @staticmethod
    def refused_args(args: list[str]) -> list[str]:
        """Arguments that would approve everything without asking (yolo mode)."""
        return [a for a in args if a.lower() in YOLO_ARGS]
