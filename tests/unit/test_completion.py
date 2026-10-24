import shutil
import subprocess

import pytest

from jigwork import cli, completion

if shutil.which("fish") is None:
    pytest.skip("fish is not installed", allow_module_level=True)


@pytest.fixture
def script(tmp_path, capsys):
    assert cli.main(["completion", "fish"]) == 0
    path = tmp_path / "jigw.fish"
    path.write_text(capsys.readouterr().out)
    return path


def complete(script, line):
    done = subprocess.run(
        ["fish", "--no-config", "-c", f"source {script}; complete -C {line!r}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [row.split("\t")[0] for row in done.stdout.splitlines()]


def test_script_is_valid_fish(script):
    assert subprocess.run(["fish", "--no-config", "-n", str(script)]).returncode == 0


def test_every_command_completes(script):
    parser = cli.build_parser()
    names = [name for name, _, _ in completion._subcommands(parser)]
    assert {
        "run",
        "resume",
        "status",
        "check",
        "init",
        "migrate",
        "server",
        "chat",
        "doctor",
    } <= set(names)
    assert set(complete(script, "jigw ")) >= set(names)
    assert set(complete(script, "jigwork ")) >= set(names)  # the long name too


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("jigw ser", ["server"]),
        ("jigw server ", ["build", "logs", "setup", "start", "status", "stop"]),
        ("jigw server stop --", ["--force", "--help"]),
        ("jigw init --type ", ["c-cpp", "generic", "python"]),
        ("jigw lang ", ["auto", "en", "tr"]),
        ("jigw run --", ["--help", "--one"]),
        ("jigw migrate --", ["--apply", "--help"]),
        ("jigw tasks ", ["lint"]),
    ],
)
def test_completions(script, line, expected):
    assert sorted(complete(script, line)) == expected


def test_descriptions_follow_the_language(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("JIGWORK_LANG", "tr")
    cli.main(["completion", "fish"])
    assert "görev listesini göster" in capsys.readouterr().out


def test_quotes_in_descriptions_are_escaped():
    assert completion._quote("it's a \\ test") == "'it\\'s a \\\\ test'"
