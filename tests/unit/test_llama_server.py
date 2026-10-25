import os
import shlex
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from jigwork import profiles
from jigwork.agents.qwen_code import settings
from jigwork.platform import systemd
from jigwork.platform.systemd import Systemd, quote
from jigwork.servers.llama_cpp import LlamaCpp

from .conftest import ROOT


def test_default_profile_matches_the_proven_setup():
    p = profiles.load(overrides={})
    assert (p.port, p.context, p.parallel, p.threads, p.cache_ram, p.fit_target) == (
        8091,
        65536,
        1,
        6,
        2048,
        1024,
    )
    assert p.model_file == Path.home() / "models/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
    assert settings.endpoint_from(p) == settings.Endpoint()  # Qwen Code side unchanged


def test_user_overrides(isolated_home):
    from jigwork import user_config

    path = user_config.config_path()
    path.parent.mkdir(parents=True)
    path.write_text('lang = "tr"\n[server]\nport = 8092\nllama_dir = "~/src/llama"\n')
    p = profiles.load()
    assert (p.port, p.llama_dir, p.base_url) == (
        8092,
        isolated_home / "src/llama",
        "http://127.0.0.1:8092/v1",
    )


def test_unknown_profile():
    with pytest.raises(profiles.ProfileError):
        profiles.load("nope/nothing", overrides={})


CONTEXT_MD_FLAGS = (
    "-m {model} --alias qwen3.6-35b-a3b --host 127.0.0.1 --port 8091 -c 65536 -np 1 "
    "--fit on --fit-target 1024 "
    "-fa on --cache-type-k q8_0 --cache-type-v q8_0 --jinja -t 6 --cache-ram 2048 --metrics "
    "--temp 0.6 --top-p 0.95 --top-k 20 --min-p 0 --presence-penalty 0"
)


def test_command_is_the_documented_one(llama):
    expected = [str(llama.binary), *CONTEXT_MD_FLAGS.format(model=llama.profile.model_file).split()]
    assert llama.has_fit() and llama.has_cuda()
    assert llama.command() == expected


def test_old_llama_cpp_falls_back_to_cpu_moe(llama, monkeypatch):
    monkeypatch.delenv("FAKE_LLAMA_FIT")
    command = llama.command()
    assert "--fit" not in command
    i = command.index("-ngl")
    assert command[i : i + 3] == ["-ngl", "99", "--cpu-moe"]


def exec_start(unit: str) -> list[str]:
    body = unit.split("ExecStart=", 1)[1].split("\nRestart=")[0]
    return shlex.split(body.replace("\\\n", " "))


@pytest.mark.parametrize("fit", [True, False])
def test_unit_matches_v0_llama_servis_ayarla(llama, monkeypatch, isolated_home, fit):
    if shutil.which("fish") is None:
        pytest.skip("fish is needed to run the v0 function")
    if not fit:
        monkeypatch.delenv("FAKE_LLAMA_FIT")
    subprocess.run(
        ["fish", str(ROOT / "legacy/qwen-kalip/kur.fish")], check=True, capture_output=True
    )
    env = {
        **os.environ,
        "LLAMA_DIZINI": str(llama.profile.llama_dir),
        "QWEN_MODEL_YOLU": str(llama.profile.model_file),
    }
    subprocess.run(
        ["fish", "-c", "llama-servis-ayarla"],
        check=True,
        capture_output=True,
        env=env,
        input="h\n",
        text=True,
    )
    v0_unit = (isolated_home / ".config/systemd/user/llama-qwen.service").read_text()
    ours = exec_start(llama.unit(fit))
    # the one deliberate addition: --metrics, for the run stats (core/stats.py)
    assert "--metrics" in ours and "--metrics" not in exec_start(v0_unit)
    assert [a for a in ours if a != "--metrics"] == exec_start(v0_unit)
    assert "Restart=on-failure" in llama.unit(fit)


def test_unit_quotes_paths_with_spaces(llama):
    p = profiles.load(overrides={"llama_dir": "/opt/my llama", "model_file": "/m/a b.gguf"})
    unit = LlamaCpp(p).unit(fit=True)
    assert exec_start(unit)[:3] == ["/opt/my llama/build/bin/llama-server", "-m", "/m/a b.gguf"]


@pytest.mark.parametrize(
    ("arg", "quoted"),
    [
        ("plain", "plain"),
        ("a b", '"a b"'),
        ('x"y', '"x\\"y"'),
        ("50%", '"50%%"'),
        ("$HOME", '"$$HOME"'),
    ],
)
def test_systemd_quote(arg, quoted):
    assert quote(arg) == quoted


def test_write_unit_backs_up_and_skips_identical(isolated_home):
    service = Systemd()
    assert service.unit_path == isolated_home / ".config/systemd/user/llama-qwen.service"
    assert service.write_unit("one\n") is None
    backup = service.write_unit("two\n", now=datetime(2026, 10, 24, 12, 0, 0))
    assert backup.name == "llama-qwen.service.backup-20261024-120000"
    assert backup.read_text() == "one\n" and service.unit_path.read_text() == "two\n"
    assert service.write_unit("two\n") is None  # unchanged: no new backup
    assert len(list(service.unit_path.parent.iterdir())) == 2


def test_unit_dir_follows_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert systemd.unit_dir() == tmp_path / "cfg/systemd/user"


def test_wait_ready(llama, fake_systemd):
    (fake_systemd / "exists").touch()
    llama.service.start()
    answers = iter([False, False, True])
    llama._health = lambda url: next(answers)
    ticks = []
    assert llama.wait_ready(tick=lambda: ticks.append(1), sleep=lambda s: None) == "ready"
    assert len(ticks) == 2
    llama._health = lambda url: False
    llama.service.stop()
    assert llama.wait_ready(sleep=lambda s: None) == "died"
    llama.service.start()
    assert llama.wait_ready(timeout=0.05, sleep=lambda s: None) == "timeout"


def test_build_steps(llama, tmp_path):
    cuda = tmp_path / "cuda.sh"
    cuda.write_text("export NVCC_CCBIN='/usr/bin/g++-14'\n")
    src = str(llama.profile.llama_dir)
    steps = llama.build_steps(cuda_profile=cuda)
    assert steps[0] == ["git", "-C", src, "pull", "--ff-only"]
    assert steps[1][:7] == [
        "cmake",
        "-S",
        src,
        "-B",
        f"{src}/build",
        "-DGGML_CUDA=ON",
        "-DCMAKE_BUILD_TYPE=Release",
    ]
    assert steps[1][-1] == "-DCMAKE_CUDA_HOST_COMPILER=/usr/bin/g++-14"
    assert steps[2][-3:] == ["llama-server", "llama-cli", "llama-bench"]
    assert "-DCMAKE_CUDA_HOST_COMPILER" not in " ".join(
        llama.build_steps(cuda_profile=tmp_path / "none")[1]
    )
