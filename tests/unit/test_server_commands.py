from jigwork import cli, profiles
from jigwork.agents.qwen_code import settings
from jigwork.commands import server as commands_server
from jigwork.servers import health, lock, session
from jigwork.servers.health import Probe
from jigwork.servers.llama_cpp import LlamaCpp

from .test_llama_server import exec_start


def test_start_without_service(llama, capsys):
    assert not commands_server.start(llama)
    assert "jigw server setup" in capsys.readouterr().err


def test_start_waits_until_ready(llama, capsys, fake_systemd, monkeypatch):
    (fake_systemd / "exists").touch()
    server = LlamaCpp(llama.profile, health=lambda url: (fake_systemd / "active").exists())
    monkeypatch.setattr(server, "wait_ready", lambda tick: "ready")
    assert commands_server.start(server)
    assert "Ready (port 8091)." in capsys.readouterr().out
    assert (fake_systemd / "active").exists()


def test_start_reports_a_dying_service(llama, capsys, fake_systemd, monkeypatch):
    (fake_systemd / "exists").touch()
    server = LlamaCpp(llama.profile, health=lambda url: False)
    monkeypatch.setattr(server, "wait_ready", lambda tick: "died")
    assert not commands_server.start(server)
    assert "stopped while loading" in capsys.readouterr().err


def test_stop_refuses_while_in_use(llama, capsys, fake_systemd):
    (fake_systemd / "exists").touch()
    (fake_systemd / "active").touch()
    with lock.using_server():
        assert commands_server.stop(llama, force=False) == 1
        assert (fake_systemd / "active").exists()
        assert "--force" in capsys.readouterr().err
        assert commands_server.stop(llama, force=True) == 0
    assert not (fake_systemd / "active").exists()


def test_stop_never_touches_a_server_started_elsewhere(llama, capsys, fake_systemd):
    (fake_systemd / "exists").touch()  # our service exists but is not running...
    ready = lambda url: Probe(health.READY)  # ...and yet something answers: not ours  # noqa: E731
    assert commands_server.stop(llama, force=True, probe_fn=ready) == 1
    assert "not jigwork's service" in capsys.readouterr().err
    assert "stop" not in (fake_systemd / "calls.log").read_text()
    assert commands_server.stop(llama, force=False, probe_fn=lambda url: Probe(health.DOWN)) == 0


def test_status(llama, capsys, fake_systemd):
    down = lambda url: Probe(health.DOWN)  # noqa: E731
    ready = lambda url: Probe(health.READY, context=65536, slots=1, model="qwen3.6-35b-a3b")  # noqa: E731
    assert commands_server.status(llama, probe_fn=down) == 0
    assert "jigw server setup" in capsys.readouterr().out
    (fake_systemd / "exists").touch()
    commands_server.status(llama, probe_fn=down)
    assert "Stopped." in capsys.readouterr().out
    commands_server.status(llama, probe_fn=ready)  # answers, our service inactive: external
    out = capsys.readouterr().out
    assert "context 65536 per slot, 1 slot(s)" in out and "never stops it" in out
    (fake_systemd / "active").touch()
    session.marker_path().parent.mkdir(parents=True, exist_ok=True)
    session.marker_path().write_text("x")
    with lock.using_server():
        commands_server.status(llama, probe_fn=lambda url: Probe(health.LOADING))
    out = capsys.readouterr().out
    assert "still loading" in out and "Started by jigwork" in out and "In use by jigwork now" in out


def test_setup_writes_the_unit(llama, capsys, fake_systemd):
    assert commands_server.setup(llama, read=lambda q: "") == 0
    unit = llama.service.unit_path.read_text()
    assert exec_start(unit) == llama.command()
    assert "--temp 0.6" in unit  # a flag stays on the same line as its value
    assert "systemctl --user daemon-reload" in (fake_systemd / "calls.log").read_text()
    assert "jigw setup" in capsys.readouterr().out


def test_setup_asks_before_restarting(llama, fake_systemd):
    (fake_systemd / "exists").touch()
    (fake_systemd / "active").touch()
    commands_server.setup(llama, read=lambda q: "")
    assert "restart" not in (fake_systemd / "calls.log").read_text()
    commands_server.setup(llama, read=lambda q: "y")
    assert "systemctl --user restart llama-qwen" in (fake_systemd / "calls.log").read_text()


def test_setup_needs_binary_and_model(llama, capsys, tmp_path):
    missing = LlamaCpp(profiles.load(overrides={"llama_dir": str(tmp_path / "x")}))
    assert commands_server.setup(missing) == 1
    assert "jigw server build" in capsys.readouterr().err
    no_model = LlamaCpp(
        profiles.load(
            overrides={"llama_dir": str(llama.profile.llama_dir), "model_file": str(tmp_path / "m")}
        )
    )
    assert commands_server.setup(no_model) == 1
    assert "model file was not found" in capsys.readouterr().err


def test_setup_warns_without_cuda_and_fit(llama, capsys, monkeypatch):
    monkeypatch.delenv("FAKE_LLAMA_CUDA")
    monkeypatch.delenv("FAKE_LLAMA_FIT")
    commands_server.setup(llama, read=lambda q: "")
    err = capsys.readouterr().err
    assert "CUDA" in err and "--fit" in err
    assert "--cpu-moe" in llama.service.unit_path.read_text()


def test_build_runs_the_steps(llama, capsys, monkeypatch, tmp_path):
    (llama.profile.llama_dir / ".git").mkdir()
    monkeypatch.setattr(
        "jigwork.commands.server.shutil.which", lambda name, path=None: "/usr/bin/nvcc"
    )
    ran = []
    assert commands_server.build(llama, run=lambda argv, env: ran.append(argv) or 0) == 0
    assert [r[0] for r in ran] == ["git", "cmake", "cmake", str(llama.binary)]
    assert commands_server.build(llama, run=lambda argv, env: 1) == 1


def test_build_needs_a_clone(llama, capsys):
    assert commands_server.build(llama) == 1
    assert "not a git clone" in capsys.readouterr().err


def test_cli_without_systemd(monkeypatch, capsys):
    monkeypatch.setattr("jigwork.platform.systemd.Systemd.available", lambda self: False)
    assert cli.main(["server", "status"]) == 1
    assert "systemctl was not found" in capsys.readouterr().err


def test_jigw_setup_writes_agent_settings_from_the_profile(isolated_home, capsys):
    from jigwork import user_config

    path = user_config.config_path()
    path.parent.mkdir(parents=True)
    path.write_text("[server]\nport = 8099\n")
    assert cli.main(["setup"]) in (0, 1)  # 1 only when bwrap is missing
    data = settings.load(settings.settings_path())
    assert data["modelProviders"]["openai"][0]["baseUrl"] == "http://127.0.0.1:8099/v1"
    assert "context 65536" in capsys.readouterr().out
