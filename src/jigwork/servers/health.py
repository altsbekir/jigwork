"""What state is the model server in, whoever started it?

llama.cpp (verified in its tools/server source, Oct 2026): GET /health answers 200 when ready
and 503 {"error": {"message": "Loading model"}} while loading; GET /props reports the real
settings (`default_generation_settings.n_ctx`, `total_slots`, `model_alias`). Other
OpenAI-compatible servers (Ollama, LM Studio) may have no /health or /props: then `ready` is
decided by GET /v1/models and the settings are unknown.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

DOWN, LOADING, READY, ERROR = "down", "loading", "ready", "error"


@dataclass(frozen=True)
class Probe:
    state: str  # down: nothing answers; loading; ready; error: something answers, but not usable
    context: int | None = None  # n_ctx per slot, when the server reports it
    slots: int | None = None
    model: str | None = None


def root_url(base_url: str) -> str:
    return re.sub(r"/v1/?$", "", base_url.rstrip("/"))


def health_url(base_url: str) -> str:
    return root_url(base_url) + "/health"


def _get(url: str, timeout: float) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as answer:
            return answer.status, answer.read()
    except urllib.error.HTTPError as exc:
        with exc:  # an error answer holds an open response too
            return exc.code, exc.read() if exc.fp else b""


def probe(base_url: str, timeout: float = 3) -> Probe:
    try:
        status, body = _get(health_url(base_url), timeout)
    except (OSError, ValueError):
        return Probe(DOWN)
    if status == 503:
        return Probe(LOADING)
    if status == 404:  # not llama.cpp: an OpenAI-compatible server without /health
        try:
            status, _ = _get(root_url(base_url) + "/v1/models", timeout)
        except (OSError, ValueError):
            return Probe(DOWN)
        return Probe(READY if status == 200 else ERROR)
    if status != 200 or b"ok" not in body:
        return Probe(ERROR)
    try:
        status, body = _get(root_url(base_url) + "/props", timeout)
        props = json.loads(body) if status == 200 else {}
    except (OSError, ValueError):
        props = {}
    settings = props.get("default_generation_settings") or {}
    return Probe(
        READY,
        context=settings.get("n_ctx") if isinstance(settings.get("n_ctx"), int) else None,
        slots=props.get("total_slots") if isinstance(props.get("total_slots"), int) else None,
        model=props.get("model_alias") if isinstance(props.get("model_alias"), str) else None,
    )


def is_healthy(base_url: str, timeout: float = 3) -> bool:
    return probe(base_url, timeout).state == READY
