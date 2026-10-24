"""Is the model server up? (llama.cpp answers GET /health with {"status":"ok"}.)"""

from __future__ import annotations

import re
import urllib.request


def health_url(base_url: str) -> str:
    return re.sub(r"/v1/?$", "", base_url.rstrip("/")) + "/health"


def is_healthy(base_url: str, timeout: float = 3) -> bool:
    try:
        with urllib.request.urlopen(health_url(base_url), timeout=timeout) as answer:
            return b"ok" in answer.read()
    except (OSError, ValueError):
        return False
