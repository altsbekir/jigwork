import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
LEGACY_ORCHESTRATOR = ROOT / "legacy" / "qwen-kalip" / "orkestra" / "orkestra.py"


@pytest.fixture(scope="session")
def legacy():
    """The v0 orchestrator module, for parity tests against the ported code."""
    spec = importlib.util.spec_from_file_location("legacy_orkestra", LEGACY_ORCHESTRATOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up there
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        del sys.modules[spec.name]


FAKE_QWEN = ROOT / "tests" / "fake_model" / "fake_qwen.py"


@pytest.fixture
def fake_qwen(tmp_path, monkeypatch):
    """Returns configure(**scenario) -> path of the argv record; use FAKE_QWEN as executable."""
    scenario_file = tmp_path / "fake-qwen-scenario.json"
    argv_file = tmp_path / "fake-qwen-argv.json"

    def configure(**scenario):
        scenario.setdefault("argv_file", str(argv_file))
        scenario_file.write_text(json.dumps(scenario))
        monkeypatch.setenv("FAKE_QWEN_SCENARIO", str(scenario_file))
        return argv_file

    return configure


FAKE_LLAMA = """#!/bin/sh
case "$1" in
  --help) echo "usage: llama-server"; [ -n "$FAKE_LLAMA_FIT" ] && echo "  --fit-target MiB";;
  --list-devices) [ -n "$FAKE_LLAMA_CUDA" ] && echo "CUDA0: NVIDIA RTX 4060" || echo "none";;
  --version) echo "version: 1 (fake)";;
esac
exit 0
"""


@pytest.fixture
def llama(isolated_home, monkeypatch):
    """A LlamaCpp server object over a fake llama-server binary and model file."""
    from jigwork import profiles
    from jigwork.servers.llama_cpp import LlamaCpp

    llama_dir = isolated_home / "llama.cpp"
    (llama_dir / "build/bin").mkdir(parents=True)
    binary = llama_dir / "build/bin/llama-server"
    binary.write_text(FAKE_LLAMA)
    binary.chmod(0o755)
    model = isolated_home / "models/model.gguf"
    model.parent.mkdir()
    model.write_text("")
    monkeypatch.setenv("FAKE_LLAMA_FIT", "1")
    monkeypatch.setenv("FAKE_LLAMA_CUDA", "1")
    profile = profiles.load(overrides={"llama_dir": str(llama_dir), "model_file": str(model)})
    return LlamaCpp(profile, health=lambda url: False)
