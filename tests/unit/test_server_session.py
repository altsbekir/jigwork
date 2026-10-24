"""Who starts and stops the model server, whoever else manages it (decisions #17)."""

import pytest

from jigwork import profiles
from jigwork.servers import health, lock, session
from jigwork.servers.health import Probe
from jigwork.servers.llama_cpp import LlamaCpp
from jigwork.servers.session import Policy, ServerSession, Unavailable

URL = "http://127.0.0.1:8091/v1"
READY = Probe(health.READY, context=65536, slots=1, model="qwen3.6-35b-a3b")


class World:
    """The fake systemd service and what the URL answers; READY exactly while it runs, unless
    `external` says something else answers there."""

    def __init__(self, fake_systemd):
        self.state = fake_systemd
        self.external: Probe | None = None
        self.loading_polls = 0
        self.says: list[tuple[str, str, dict]] = []

    def install(self):
        (self.state / "exists").touch()

    def probe(self, url):
        if self.external is not None:
            return self.external
        if not (self.state / "active").exists():
            return Probe(health.DOWN)
        if self.loading_polls > 0:
            self.loading_polls -= 1
            return Probe(health.LOADING)
        return READY

    def say(self, level, key, **fields):
        self.says.append((level, key, fields))

    def keys(self):
        return [k for _, k, _ in self.says]

    def calls(self):
        log = self.state / "calls.log"
        return log.read_text() if log.exists() else ""


@pytest.fixture
def world(fake_systemd):
    return World(fake_systemd)


DEFAULT = Policy()


def make(world, policy=DEFAULT, url=URL, context=65536, model="qwen3.6-35b-a3b", lazy=False):
    server = LlamaCpp(profiles.load(overrides={}))
    return ServerSession(
        url,
        server,
        context,
        model,
        policy,
        world.say,
        probe_fn=world.probe,
        sleep=lambda s: None,
        lazy=lazy,
    )


def test_running_server_is_used_and_never_stopped(world):
    world.install()
    (world.state / "active").touch()  # started by the user before the run
    with make(world):
        pass
    assert "start" not in world.calls() and "stop" not in world.calls()
    assert (world.state / "active").exists()


def test_stopped_service_is_started_and_stopped_after(world):
    world.install()
    with make(world):
        assert (world.state / "active").exists()
        assert session.marker_path().read_text() == (world.state / "invocation").read_text()
    assert not (world.state / "active").exists()
    assert not session.marker_path().exists()
    assert world.keys() == ["session.starting", "session.stopping"]


def test_stop_when_done_false_keeps_it_running(world):
    world.install()
    with make(world, Policy(stop_when_done=False)):
        pass
    assert (world.state / "active").exists()
    assert session.marker_path().exists()  # still jigwork's: a later run with true stops it
    with make(world):
        pass
    assert not (world.state / "active").exists()


def test_kept_up_while_the_run_waits_for_the_user(world):
    world.install()
    with make(world) as server_session:
        server_session.keep_up()
    assert (world.state / "active").exists()
    assert world.keys() == ["session.starting", "session.kept_up"]
    with make(world):  # `jigw resume` uses it and stops it when it ends normally
        pass
    assert not (world.state / "active").exists()
    assert [c for c in world.calls().split() if c == "start"] == ["start"]  # started once


def test_lazy_session_not_needed_starts_nothing(world):
    world.install()
    with make(world, lazy=True):
        pass  # `jigw resume` whose checks passed
    assert "start" not in world.calls() and world.keys() == []


def test_lazy_session_starts_when_the_agent_needs_it(world):
    world.install()
    with make(world, lazy=True) as server_session:
        assert "start" not in world.calls()
        assert server_session.is_up()
        assert (world.state / "active").exists()
    assert world.keys() == ["session.starting", "session.stopping"]


def test_lazy_session_stops_a_server_kept_up_for_it(world):
    world.install()
    with make(world) as server_session:
        server_session.keep_up()
    with make(world, lazy=True):
        pass  # resume did not need it, but it was kept up only for this resume
    assert not (world.state / "active").exists()


def test_lazy_open_that_fails_is_reported_once(world):
    with make(world, lazy=True) as server_session:  # nothing installed, nothing answers
        assert not server_session.is_up()
        assert not server_session.wait_back()
        assert not server_session.is_up()
    assert world.keys() == ["session.down"]


def test_manage_never_does_not_start(world):
    world.install()
    with pytest.raises(Unavailable) as error:
        make(world, Policy(manage="never")).__enter__()
    assert error.value.key == "session.down"
    assert "start" not in world.calls()
    assert lock.active_users() == []  # the usage entry is released on failure too


def test_no_service_to_start(world):
    with pytest.raises(Unavailable) as error:
        make(world).__enter__()
    assert error.value.key == "session.down"


def test_another_url_is_never_managed(world):
    world.install()
    with pytest.raises(Unavailable):
        make(world, url="http://10.0.0.5:9000/v1").__enter__()
    assert "start" not in world.calls()


def test_external_server_on_our_port_is_used_not_stopped(world):
    world.install()
    world.external = READY  # our service is off, but a hand-started llama-server answers
    with make(world):
        pass
    assert "start" not in world.calls() and "stop" not in world.calls()


def test_restarted_by_someone_else_is_theirs(world):
    world.install()
    with make(world):
        (world.state / "invocation").write_text("restarted-by-the-user")
    assert (world.state / "active").exists()
    assert not session.marker_path().exists()


def test_not_stopped_while_another_jigwork_run_uses_it(world, monkeypatch):
    world.install()
    with make(world):
        monkeypatch.setattr(lock, "active_users", lambda: [1, __import__("os").getpid()])
    assert (world.state / "active").exists()


def test_waits_while_loading(world):
    world.install()
    world.loading_polls = 3
    with make(world):
        pass
    assert "session.loading" in world.keys()


def test_service_dying_while_loading(world, monkeypatch):
    world.install()
    (world.state / "start-fails").touch()
    with pytest.raises(Unavailable) as error:
        make(world).__enter__()
    assert error.value.key == "session.start_failed"


def test_server_with_a_smaller_context_is_refused(world):
    world.external = Probe(health.READY, context=32768, slots=1, model="qwen3.6-35b-a3b")
    with pytest.raises(Unavailable) as error:
        make(world).__enter__()
    assert (error.value.key, error.value.fields) == (
        "session.context_too_small",
        {"server": 32768, "agent": 65536},
    )


def test_other_model_is_a_warning(world):
    world.external = Probe(health.READY, context=65536, model="llama-3")
    with make(world):
        pass
    assert (
        "warn",
        "session.other_model",
        {"server": "llama-3", "agent": "qwen3.6-35b-a3b"},
    ) in world.says


def test_unknown_settings_are_accepted(world):
    world.external = Probe(health.READY)  # e.g. Ollama: no /props
    with make(world):
        pass


def test_wait_back_never_restarts(world):
    world.install()
    (world.state / "active").touch()
    run = make(world, Policy(outage_wait=0))
    with run:
        (world.state / "active").unlink()  # the user stopped it during the run
        assert not run.is_up()
        assert not run.wait_back()
        assert "start" not in world.calls()


def test_wait_back_when_it_returns(world, monkeypatch):
    world.install()
    (world.state / "active").touch()
    run = make(world)
    with run:
        answers = iter([Probe(health.DOWN), Probe(health.LOADING), READY])
        run._probe = lambda url: next(answers)
        assert run.wait_back()
    assert world.keys()[-2:] == ["session.lost", "session.back"]


def test_policy_from_user_config(isolated_home):
    from jigwork import user_config

    path = user_config.config_path()
    path.parent.mkdir(parents=True)
    path.write_text('[server]\nmanage = "never"\nstop_when_done = false\noutage_wait = 30\n')
    assert session.policy() == Policy(manage="never", stop_when_done=False, outage_wait=30)
    path.write_text('[server]\nmanage = "sometimes"\n')
    assert session.policy().manage == "auto"
