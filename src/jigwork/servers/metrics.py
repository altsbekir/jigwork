"""The model server's own counters, read before and after an agent session.

llama.cpp (verified in tools/server/server-task.cpp, Oct 2026): GET /metrics answers in the
Prometheus text format when the server runs with `--metrics` (otherwise 501). The counters
used here are totals since the server started, so one session's share is a difference:
`llamacpp:prompt_tokens_total` (excluding cached tokens), `prompt_tokens_cached_total`,
`prompt_seconds_total`, `tokens_predicted_total`, `tokens_predicted_seconds_total`.

The difference is exact while only this session uses the server; jigwork's usage lock keeps
other jigwork runs away, but a chat in another terminal would be counted too.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from jigwork.servers.health import root_url

COUNTERS = {
    "prompt_tokens_total": "prompt_tokens",
    "prompt_tokens_cached_total": "cached_tokens",
    "prompt_seconds_total": "prompt_seconds",
    "tokens_predicted_total": "generated_tokens",
    "tokens_predicted_seconds_total": "generation_seconds",
}
LINE = re.compile(r"^llamacpp:(\w+)\s+([0-9.eE+-]+)\s*$", re.M)


@dataclass(frozen=True)
class ServerCounters:
    prompt_tokens: float = 0
    cached_tokens: float = 0
    prompt_seconds: float = 0
    generated_tokens: float = 0
    generation_seconds: float = 0

    def minus(self, earlier: ServerCounters) -> ServerCounters:
        return ServerCounters(
            *(getattr(self, k) - getattr(earlier, k) for k in self.__dataclass_fields__)
        )

    @property
    def generation_rate(self) -> float | None:
        """Generated tokens per second, None when nothing was generated."""
        return self.generated_tokens / self.generation_seconds if self.generation_seconds else None

    @property
    def prompt_rate(self) -> float | None:
        return self.prompt_tokens / self.prompt_seconds if self.prompt_seconds else None


def parse(text: str) -> ServerCounters | None:
    found = {}
    for name, value in LINE.findall(text):
        if name in COUNTERS:
            try:
                found[COUNTERS[name]] = float(value)
            except ValueError:
                continue
    return ServerCounters(**found) if found else None


def read(base_url: str, timeout: float = 3) -> ServerCounters | None:
    """None: no /metrics (another server, or llama.cpp without --metrics), or no answer."""
    try:
        with urllib.request.urlopen(root_url(base_url) + "/metrics", timeout=timeout) as answer:
            if answer.status != 200:
                return None
            return parse(answer.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        exc.close()
        return None
    except (OSError, ValueError):
        return None
