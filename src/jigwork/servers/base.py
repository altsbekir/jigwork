"""What the commands need from a model server."""

from __future__ import annotations

from typing import Protocol


class ModelServer(Protocol):
    def health(self) -> bool: ...

    def start(self) -> bool: ...

    def stop(self) -> bool: ...
