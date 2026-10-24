import os
import subprocess
import sys
from pathlib import Path

import pytest

from jigwork import COMMAND, __version__
from jigwork.cli import main


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"{COMMAND} {__version__}"


def test_no_command_prints_usage_and_fails(capsys):
    assert main([]) == 2
    assert "usage:" in capsys.readouterr().err


def test_unknown_command_fails():
    with pytest.raises(SystemExit) as exc:
        main(["no-such-command"])
    assert exc.value.code == 2


def test_python_dash_m():
    result = subprocess.run(
        [sys.executable, "-m", "jigwork", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert __version__ in result.stdout


def test_home_is_isolated(isolated_home):
    assert Path(os.environ["HOME"]) == isolated_home
