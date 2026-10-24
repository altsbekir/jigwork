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
