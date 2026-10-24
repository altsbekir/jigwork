"""The model server for the length of one `jigw run` / `jigw chat`, whoever manages it.

Rules (docs/decisions.md #17):
* A server that was already up is used and never stopped by jigwork.
* A server that is down is started only if it is jigwork's systemd service and the user did
  not set `[server] manage = "never"`; jigwork then remembers the service's InvocationID.
* At the end, a server jigwork started is stopped when `stop_when_done` (default true), unless
  another jigwork process still uses it, or someone restarted it meanwhile (new InvocationID).
  A run that stops to wait for the user (`keep_up()`: commands to run, then `jigw resume`)
  leaves it up; the next session that ends normally stops it.
* `lazy=True` (`jigw resume`): the server is opened only when the agent is about to run; a
  resume whose checks pass needs no model at all.
* If the server goes away during a run, jigwork waits up to `outage_wait` seconds for it to
  come back. It never restarts a server someone else stopped.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jigwork import user_config
from jigwork.core.checks import cache_dir
from jigwork.i18n import t
from jigwork.servers import lock
from jigwork.servers.health import DOWN, ERROR, LOADING, READY, Probe, probe
from jigwork.servers.llama_cpp import LlamaCpp

MANAGE = ("auto", "never")


@dataclass(frozen=True)
class Policy:
    manage: str = "auto"
    stop_when_done: bool = True
    outage_wait: int = 300  # seconds to wait for a server that went away during a run
    load_wait: int = 600  # seconds to wait for a model that is loading


def policy() -> Policy:
    try:
        server = user_config.load().get("server", {})
    except user_config.ConfigError:
        server = {}
    server = server if isinstance(server, dict) else {}
    manage = str(server.get("manage", "auto"))
    return Policy(
        manage=manage if manage in MANAGE else "auto",
        stop_when_done=bool(server.get("stop_when_done", True)),
        outage_wait=int(server.get("outage_wait", 300)),
        load_wait=int(server.get("load_wait", 600)),
    )


def marker_path() -> Path:
    """The InvocationID of the service run jigwork started (absent: jigwork started none)."""
    return cache_dir() / "server-started-by-jigwork"


class Unavailable(Exception):
    """The server cannot be used; `key` names an i18n message."""

    def __init__(self, key: str, **fields: object) -> None:
        super().__init__(key)
        self.key = key
        self.fields = fields


Say = Callable[..., None]


class ServerSession:
    def __init__(
        self,
        url: str,
        server: LlamaCpp | None,
        expected_context: int | None,
        expected_model: str | None,
        policy: Policy,
        say: Say,
        probe_fn: Callable[[str], Probe] = probe,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        lazy: bool = False,
    ) -> None:
        self.url = url
        self.server = server
        self.expected_context = expected_context
        self.expected_model = expected_model
        self.policy = policy
        self.say = say
        self._probe = probe_fn
        self._sleep = sleep
        self._clock = clock
        self._lock = None
        self._keep = False
        self._lazy = lazy
        self._opened = False  # False: lazy and not needed yet, or opening it failed
        self._failed = False

    # --- helpers ----------------------------------------------------------------------------

    def _ours(self) -> bool:
        """The URL is the one jigwork's own systemd service serves."""
        return (
            self.server is not None
            and self.policy.manage == "auto"
            and self.server.service.available()
            and self.server.service.exists()
            and self.url.rstrip("/") == self.server.profile.base_url
        )

    def _wait(
        self, seconds: float, until: Callable[[Probe], bool], tick: Callable[[], None]
    ) -> Probe:
        deadline = self._clock() + seconds
        state = self._probe(self.url)
        while not until(state) and self._clock() < deadline:
            tick()
            self._sleep(2)
            state = self._probe(self.url)
        return state

    def _check_settings(self, state: Probe) -> None:
        if self.expected_context and state.context and state.context < self.expected_context:
            raise Unavailable(
                "session.context_too_small", server=state.context, agent=self.expected_context
            )
        if self.expected_model and state.model and state.model != self.expected_model:
            self.say("warn", "session.other_model", server=state.model, agent=self.expected_model)

    # --- lifecycle --------------------------------------------------------------------------

    def __enter__(self) -> ServerSession:
        self._lock = lock.using_server()
        self._lock.__enter__()
        if self._lazy:
            return self
        try:
            self._open()
            self._opened = True
        except BaseException:
            self._lock.__exit__(None, None, None)
            raise
        return self

    def _open(self) -> None:
        state = self._probe(self.url)
        if state.state == DOWN:
            marker_path().unlink(missing_ok=True)  # whatever jigwork started is gone
            if not self._ours():
                raise Unavailable("session.down", url=self.url)
            self.say("info", "session.starting")
            if not self.server.service.start():
                raise Unavailable("session.start_failed")
            invocation = self.server.service.invocation_id()
            if invocation:
                marker_path().parent.mkdir(parents=True, exist_ok=True)
                marker_path().write_text(invocation)
            state = self._probe(self.url)
        if state.state in (LOADING, DOWN):
            self.say("info", "session.loading")
            state = self._wait(
                self.policy.load_wait,
                lambda s: s.state in (READY, ERROR) or (s.state == DOWN and not self._service_up()),
                lambda: None,
            )
        if state.state != READY:
            raise Unavailable("session.not_ready", url=self.url, state=t(f"state.{state.state}"))
        self._check_settings(state)

    def _service_up(self) -> bool:
        return self.server is not None and self.server.service.is_active()

    def __exit__(self, *exc) -> None:
        try:
            self._close()
        finally:
            self._lock.__exit__(*exc)

    def _close(self) -> None:
        marker = marker_path()
        if not (self.policy.stop_when_done and marker.exists() and self._ours()):
            return
        if not self._opened and not self.server.service.is_active():
            return  # never needed, and not running anyway
        if self._keep:
            self.say("info", "session.kept_up")
            return
        if [pid for pid in lock.active_users() if pid != os.getpid()]:
            return  # another jigwork run still uses it
        if self.server.service.invocation_id() != marker.read_text().strip():
            marker.unlink(missing_ok=True)  # restarted by someone else: theirs now
            return
        self.say("info", "session.stopping")
        if self.server.service.stop():
            marker.unlink(missing_ok=True)

    def keep_up(self) -> None:
        """The run waits for the user and will be resumed: do not stop the server at the end."""
        self._keep = True

    # --- during the run ---------------------------------------------------------------------

    def _ensure_open(self) -> bool:
        if self._opened or self._failed:
            return self._opened
        try:
            self._open()
        except Unavailable as unavailable:
            self.say("error", unavailable.key, **unavailable.fields)
            self._failed = True
            return False
        self._opened = True
        return True

    def is_up(self) -> bool:
        if not self._ensure_open():
            return False
        return self._probe(self.url).state == READY

    def wait_back(self) -> bool:
        """After an outage: wait for the server to answer again; never start it ourselves."""
        if not self._ensure_open():
            return False  # a lazy open failed: the message says why, waiting will not help
        self.say("warn", "session.lost", seconds=self.policy.outage_wait)
        state = self._wait(self.policy.outage_wait, lambda s: s.state == READY, lambda: None)
        if state.state == READY:
            self._check_settings(state)
            self.say("ok", "session.back")
            return True
        return False
