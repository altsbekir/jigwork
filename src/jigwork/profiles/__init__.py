"""Model + hardware profiles: `profiles/<model>/<hardware>.toml` (decisions #10).

A profile holds what is specific to one model on one machine: the server flags, the context
size, threads, offload and sampling. The user picks one and may override paths and the port in
`~/.config/jigwork/config.toml`:

    [server]
    profile = "qwen3.6-35b-a3b/rtx4060-laptop-8gb"
    llama_dir = "~/llama.cpp"
    model_file = "~/models/other.gguf"
    port = 8092
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from jigwork import user_config

DEFAULT = "qwen3.6-35b-a3b/rtx4060-laptop-8gb"
DEFAULT_LLAMA_DIR = "~/llama.cpp"


class ProfileError(Exception):
    pass


@dataclass(frozen=True)
class Profile:
    name: str
    model_id: str
    display_name: str
    model_file: Path
    host: str
    port: int
    context: int
    parallel: int
    threads: int
    cache_ram: int
    fit_target: int
    fallback_offload: list[str]
    flags: list[str]
    sampling: dict = field(default_factory=dict)
    llama_dir: Path = Path(DEFAULT_LLAMA_DIR).expanduser()

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}/v1"


def available() -> list[str]:
    root = resources.files(__name__)
    return sorted(
        f"{model.name}/{hw.name.removesuffix('.toml')}"
        for model in root.iterdir()
        if model.is_dir() and not model.name.startswith("_")
        for hw in model.iterdir()
        if hw.name.endswith(".toml")
    )


def load(name: str | None = None, overrides: dict | None = None) -> Profile:
    """The profile `name` (default: the user's choice, else DEFAULT) with the user's overrides."""
    if overrides is None:
        try:
            server = user_config.load().get("server", {})
        except user_config.ConfigError:
            server = {}
        overrides = server if isinstance(server, dict) else {}
    name = name or str(overrides.get("profile") or DEFAULT)
    if name not in available():
        raise ProfileError(f"unknown profile {name!r} (available: {', '.join(available())})")
    text = resources.files(__name__).joinpath(f"{name}.toml").read_text(encoding="utf-8")
    data = tomllib.loads(text)
    model, server, sampling = data["model"], data["server"], data["sampling"]
    try:
        return Profile(
            name=name,
            model_id=model["id"],
            display_name=model["display_name"],
            model_file=Path(str(overrides.get("model_file", model["file"]))).expanduser(),
            host=server["host"],
            port=int(overrides.get("port", server["port"])),
            context=int(server["context"]),
            parallel=int(server["parallel"]),
            threads=int(server["threads"]),
            cache_ram=int(server["cache_ram"]),
            fit_target=int(server["fit_target"]),
            fallback_offload=[str(x) for x in server["fallback_offload"]],
            flags=[str(x) for x in server["flags"]],
            sampling=dict(sampling),
            llama_dir=Path(str(overrides.get("llama_dir", DEFAULT_LLAMA_DIR))).expanduser(),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProfileError(f"profile {name}: {exc}") from exc
