"""`jigw server start|stop|status|logs|setup|build`: the local model server jigwork manages."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable

from jigwork import profiles, ui
from jigwork.commands import common
from jigwork.i18n import t
from jigwork.servers import health, lock, session
from jigwork.servers.llama_cpp import LlamaCpp, cuda_path_env


def _server() -> LlamaCpp | None:
    try:
        return LlamaCpp(profiles.load())
    except profiles.ProfileError as exc:
        common.err(t("server.bad_profile", error=str(exc)))
        return None


def start(server: LlamaCpp, quiet_if_running: bool = False) -> bool:
    """Start the service and wait until the model is loaded (v0 `qwen-sunucu baslat`)."""
    if not server.service.exists():
        common.err(t("server.no_service", name=server.service.service))
        return False
    if server.health():
        if not quiet_if_running:
            print(t("server.already_running", port=server.profile.port))
        return True
    if not server.service.is_active() and not server.service.start():
        common.err(t("server.start_failed"))
        return False
    print(t("server.loading"), end="", flush=True)
    outcome = server.wait_ready(tick=lambda: print(".", end="", flush=True))
    print()
    if outcome == "ready":
        print(t("server.ready", port=server.profile.port))
        return True
    common.err(t("server.died") if outcome == "died" else t("server.timeout"))
    return False


def stop(server: LlamaCpp, force: bool, probe_fn=health.probe) -> int:
    if not server.service.is_active():
        if probe_fn(server.profile.base_url).state == health.DOWN:
            print(t("server.off"))
            return 0
        common.err(t("server.not_ours", url=server.profile.base_url))  # never stop theirs
        return 1
    users = lock.active_users()
    if users and not force:
        common.err(t("server.in_use", pids=", ".join(map(str, users))))
        return 1
    if not server.service.stop():
        common.err(t("server.stop_failed"))
        return 1
    session.marker_path().unlink(missing_ok=True)
    print(t("server.stopped"))
    return 0


def status(server: LlamaCpp, probe_fn=health.probe) -> int:
    p = server.profile
    print(t("server.profile", name=p.name, url=p.base_url))
    state = probe_fn(p.base_url)
    active = server.service.exists() and server.service.is_active()
    if state.state == health.DOWN:
        print(
            t("server.off")
            if server.service.exists()
            else t("server.no_service", name=server.service.service)
        )
    elif state.state == health.LOADING:
        print(t("server.on_loading"))
    elif state.state == health.ERROR:
        print(t("server.answers_oddly", url=p.base_url))
    else:
        print(t("server.on_ready", port=p.port))
        if state.context is not None:
            print(t("server.reported", context=state.context, slots=state.slots, model=state.model))
    if state.state != health.DOWN:
        if not active:
            print(t("server.external"))
        elif session.marker_path().exists():
            print(t("server.started_by_jigwork"))
    if users := lock.active_users():
        print(t("server.in_use_now", pids=", ".join(map(str, users))))
    return 0


def setup(server: LlamaCpp, read: Callable[[str], str] = input) -> int:
    """Write the systemd unit from the profile (v0 `llama-servis-ayarla`)."""
    p = server.profile
    if not server.binary.exists():
        common.err(t("server.no_binary", path=server.binary))
        return 1
    if not p.model_file.exists():
        common.err(t("server.no_model", path=p.model_file))
        return 1
    if not server.has_cuda():
        common.err(t("server.no_cuda"))
    fit = server.has_fit()
    if not fit:
        common.err(t("server.no_fit"))
    backup = server.service.write_unit(server.unit(fit))
    if backup:
        print(t("server.unit_backup", path=backup))
    print(t("server.unit_written", path=server.service.unit_path, port=p.port, context=p.context))
    server.service.daemon_reload()
    if server.service.is_active():
        if ui.confirm(t("server.restart_confirm"), default=False, read=read):
            server.service.restart()
            print(t("server.restarted"))
        else:
            print(t("server.restart_later"))
    print(t("server.sync_agent"))
    return 0


def build(server: LlamaCpp, run: Callable[..., int] = subprocess.call) -> int:
    """git pull + CUDA build (v0 `llama-guncelle`)."""
    src = server.profile.llama_dir
    if not (src / ".git").is_dir():
        common.err(t("server.not_a_clone", path=src))
        return 1
    env = cuda_path_env()
    if not shutil.which("nvcc", path=env.get("PATH")):
        common.err(t("server.no_nvcc"))
        return 1
    for step in server.build_steps():
        print(t("server.build_step", command=" ".join(step)), flush=True)
        if run(step, env=env) != 0:
            common.err(t("server.build_failed"))
            return 1
    run([str(server.binary), "--version"], env=env)
    print(t("server.build_done"))
    return 0


def run(action: str, force: bool = False) -> int:
    server = _server()
    if server is None:
        return 1
    if not server.service.available():
        common.err(t("server.no_systemd"))
        return 1
    if action == "start":
        return 0 if start(server) else 1
    if action == "stop":
        return stop(server, force)
    if action == "status":
        return status(server)
    if action == "logs":
        return server.service.logs()
    if action == "setup":
        return setup(server)
    if action == "build":
        return build(server)
    raise ValueError(action)
