import pytest

from jigwork.core import project
from jigwork.core.project import PYTHON_AUTOFIX, ConfigError, load

from .conftest import ROOT


def test_defaults_without_config(tmp_path):
    p = load(tmp_path)
    assert (p.config_path, p.legacy, p.config.prepare, p.config.autofix, p.config.checks) == (
        None,
        False,
        "none",
        "",
        {},
    )
    assert p.config.skills["fix"] == ["fix-failing-checks"]
    assert p.config.limits == project.Limits()
    assert p.work_dir == tmp_path / ".jigwork/work"


def test_python_defaults(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    p = load(tmp_path)
    assert (p.config.prepare, p.config.autofix) == ("python-venv", PYTHON_AUTOFIX)


def test_v1_config(tmp_path):
    (tmp_path / ".jigwork").mkdir()
    (tmp_path / ".jigwork/config.toml").write_text(
        '[prepare]\nkind = "none"\n[autofix]\ncommand = "fmt"\n'
        '[checks]\nlint = "ruff check ."\ntest = "pytest"\n'
        '[skills]\ncode = ["x-*"]\n[limits]\nattempts = 2\nagent_wall_time = "5m"\n'
    )
    p = load(tmp_path)
    assert list(p.config.checks) == ["lint", "test"]
    assert p.config.autofix == "fmt"
    assert p.config.skills["code"] == ["x-*"] and p.config.skills["test"] == ["*-test"]
    assert (p.config.limits.attempts, p.config.limits.agent_wall_time) == (2, "5m")


@pytest.mark.parametrize(
    "template",
    [
        "paketler/python/.kalip/kontroller.toml",
        "paketler/c-cpp/.kalip/kontroller.toml",
        "ortak/.kalip/kontroller.toml",
    ],
)
def test_v0_config_matches_v0_reader(tmp_path, legacy, template):
    (tmp_path / ".kalip").mkdir()
    (tmp_path / ".kalip/kontroller.toml").write_text(
        (ROOT / "legacy/qwen-kalip" / template).read_text()
    )
    if "python" in template:
        (tmp_path / "pyproject.toml").write_text("")
    old, new = legacy.ayarlari_oku(tmp_path), load(tmp_path)
    assert new.legacy and new.work_dir == tmp_path / ".kalip/calisma"
    assert new.config.checks == old["kontroller"]
    assert new.config.prepare == {"yok": "none"}.get(old["hazirlik"]["tur"], old["hazirlik"]["tur"])
    assert new.config.autofix == old.get("oto_duzeltme", {}).get("komut", "")
    for v0, v1 in project.V0_SKILL_TYPES.items():
        assert new.config.skills[v1] == old["skills"][v0]
    o = old["orkestra"]
    assert (new.config.limits.attempts, new.config.limits.agent_wall_time) == (
        o["max_deneme"],
        o["qwen_sure"],
    )
    assert (new.config.limits.agent_tool_calls, new.config.limits.check_timeout) == (
        o["max_arac"],
        o["kontrol_sure_sn"],
    )


def test_v0_project_without_hazirlik_guesses_like_v0(tmp_path, legacy):
    (tmp_path / ".kalip").mkdir()
    (tmp_path / ".kalip/kontroller.toml").write_text('[kontroller]\nlint = "ruff check ."\n')
    (tmp_path / "pyproject.toml").write_text("")
    assert (
        load(tmp_path).config.prepare
        == "python-venv"
        == legacy.ayarlari_oku(tmp_path)["hazirlik"]["tur"]
    )


def test_v1_config_wins_over_v0(tmp_path):
    (tmp_path / ".kalip").mkdir()
    (tmp_path / ".kalip/kontroller.toml").write_text('[kontroller]\nold = "x"\n')
    (tmp_path / ".jigwork").mkdir()
    (tmp_path / ".jigwork/config.toml").write_text('[checks]\nnew = "y"\n')
    p = load(tmp_path)
    assert (p.legacy, list(p.config.checks)) == (False, ["new"])


@pytest.mark.parametrize(
    "text",
    [
        "[checks\n",
        'checks = "x"\n',
        "[checks]\nlint = 3\n",
        '[prepare]\nkind = "docker"\n',
        "[skills]\ncode = 'x'\n",
        "[limits]\nattempts = 0\n",
        '[limits]\nattempts = "many"\n',
    ],
)
def test_bad_config(tmp_path, text):
    (tmp_path / ".jigwork").mkdir()
    (tmp_path / ".jigwork/config.toml").write_text(text)
    with pytest.raises(ConfigError):
        load(tmp_path)
