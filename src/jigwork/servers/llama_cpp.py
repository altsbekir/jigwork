"""llama.cpp's llama-server run as a systemd user service, from a profile.

Port of v0 `qwen-sunucu`, `llama-servis-ayarla` and `llama-guncelle`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from jigwork.platform.systemd import Systemd, unit_text
from jigwork.profiles import Profile
from jigwork.servers.health import is_healthy

UNIT_HEADER = "Written by jigwork. To rewrite it: jigw server setup"


class LlamaCpp:
    def __init__(self, profile: Profile, service: Systemd | None = None, health=is_healthy) -> None:
        self.profile = profile
        self.service = service or Systemd()
        self._health = health

    @property
    def binary(self) -> Path:
        return self.profile.llama_dir / "build" / "bin" / "llama-server"

    def _probe(self, *args: str) -> str:
        try:
            done = subprocess.run(
                [str(self.binary), *args], capture_output=True, text=True, timeout=60
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return done.stdout + done.stderr

    def has_fit(self) -> bool:
        """Newer llama.cpp fills the GPU itself (--fit); older needs explicit offload flags."""
        return "--fit-target" in self._probe("--help")

    def has_cuda(self) -> bool:
        return "cuda" in self._probe("--list-devices").lower()

    def command(self, fit: bool | None = None) -> list[str]:
        p = self.profile
        fit = self.has_fit() if fit is None else fit
        offload = ["--fit", "on", "--fit-target", str(p.fit_target)] if fit else p.fallback_offload
        sampling = p.sampling
        return [
            str(self.binary),
            "-m", str(p.model_file),
            "--alias", p.model_id,
            "--host", p.host, "--port", str(p.port),
            "-c", str(p.context), "-np", str(p.parallel),
            *offload,
            *p.flags,
            "-t", str(p.threads), "--cache-ram", str(p.cache_ram),
            "--metrics",  # GET /metrics: exact token/time counters for the run stats
            "--temp", str(sampling["temperature"]), "--top-p", str(sampling["top_p"]),
            "--top-k", str(sampling["top_k"]), "--min-p", str(sampling["min_p"]),
            "--presence-penalty", str(sampling["presence_penalty"]),
        ]  # fmt: skip

    def unit(self, fit: bool | None = None) -> str:
        return unit_text(
            f"llama.cpp server - {self.profile.display_name}", self.command(fit), UNIT_HEADER
        )

    # --- running ----------------------------------------------------------------------------

    def health(self) -> bool:
        return self._health(self.profile.base_url)

    def start(self) -> bool:
        return self.service.start()

    def stop(self) -> bool:
        return self.service.stop()

    def wait_ready(
        self,
        timeout: float = 600,
        tick: Callable[[], None] = lambda: None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> str:
        """ "ready", "died" (the service stopped while loading) or "timeout"."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.health():
                return "ready"
            if not self.service.is_active():
                return "died"
            tick()
            sleep(1)
        return "timeout"

    # --- building ---------------------------------------------------------------------------

    def build_steps(self, cuda_profile: Path = Path("/etc/profile.d/cuda.sh")) -> list[list[str]]:
        """git pull + CUDA build of llama-server (v0 `llama-guncelle`)."""
        src = str(self.profile.llama_dir)
        extra = []
        if cuda_profile.exists():
            match = re.search(r"NVCC_CCBIN=['\"]?([^'\" \n]+)", cuda_profile.read_text())
            if match:  # Arch's cuda package names the GCC it supports
                extra.append(f"-DCMAKE_CUDA_HOST_COMPILER={match.group(1)}")
        build = f"{src}/build"
        jobs = str(os.cpu_count() or 4)
        return [
            ["git", "-C", src, "pull", "--ff-only"],
            ["cmake", "-S", src, "-B", build, "-DGGML_CUDA=ON", "-DCMAKE_BUILD_TYPE=Release",
             *extra],
            ["cmake", "--build", build, "--config", "Release", "-j", jobs,
             "--target", "llama-server", "llama-cli", "llama-bench"],
        ]  # fmt: skip


def cuda_path_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """PATH with /opt/cuda/bin when nvcc is not found (fish does not read /etc/profile.d)."""
    env = dict(os.environ if env is None else env)
    if not shutil.which("nvcc", path=env.get("PATH")) and Path("/opt/cuda/bin/nvcc").exists():
        env["PATH"] = f"/opt/cuda/bin:{env.get('PATH', '')}"
    return env
