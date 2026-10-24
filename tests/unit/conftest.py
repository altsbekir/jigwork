import importlib.util
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
