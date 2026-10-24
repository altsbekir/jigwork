from pathlib import Path

import pytest

from jigwork.core.git_guard import protected_paths
from jigwork.sandbox.bwrap import BwrapSandbox


@pytest.fixture
def project(isolated_home):
    path = isolated_home / "proj"
    for name in (".git", ".qwen", ".kalip", "docs"):
        (path / name).mkdir(parents=True)
    for name in ("AGENTS.md", "docs/TASKS.md", "pyproject.toml"):
        (path / name).write_text("")
    return path


def test_command_matches_v0(project, isolated_home, legacy):
    venv = isolated_home / ".cache/qwen-kalip/venv/proj-1"
    readonly = [project / k for k in legacy.KORUNAN]
    for tool in (None, venv):
        ours = BwrapSandbox().command(
            project,
            "pytest -q",
            readonly=readonly,
            extra_ro_mounts=[tool] if tool else [],
            path_prepend=[tool / "bin"] if tool else [],
        )
        assert ours == legacy.kutu_komutu(project, tool, "pytest -q")


def test_protected_paths_are_mounted_read_only(project):
    (project / ".env").write_text("")
    (project / ".env.local").write_text("")
    argv = BwrapSandbox().command(project, "true", readonly=protected_paths(project))
    mounted = {argv[i + 1] for i, a in enumerate(argv) if a == "--ro-bind"}
    for name in (".git", ".qwen", ".kalip", "AGENTS.md", "docs/TASKS.md", ".env", ".env.local"):
        assert str(project / name) in mounted
    assert str(project / "docs") not in mounted


def test_project_and_hidden_dirs_come_before_read_only_mounts(project, isolated_home):
    argv = BwrapSandbox().command(project, "true", readonly=[project / ".git"])
    assert argv.index(str(isolated_home)) < argv.index(str(project))
    bind = argv.index("--bind")
    assert argv.index("--ro-bind", bind) > bind  # .git read-only on top of the writable project


@pytest.mark.parametrize("where", ["/", "home", "above_home"])
def test_refuses_project_that_would_expose_home(isolated_home, where):
    project = {"/": Path("/"), "home": isolated_home, "above_home": isolated_home.parent}[where]
    with pytest.raises(ValueError):
        BwrapSandbox().command(project, "true")


def test_refuses_read_only_path_outside_project(project, isolated_home):
    for outside in (isolated_home / "elsewhere", project / ".." / "elsewhere"):
        with pytest.raises(ValueError):
            BwrapSandbox().command(project, "true", readonly=[outside])


def test_symlinked_protected_path_is_not_mounted(project, isolated_home):
    secret = isolated_home / "secret"
    secret.write_text("key")
    (project / ".env.x").symlink_to(secret)
    (project / "linked-dir").symlink_to(isolated_home)
    readonly = [project / ".env.x", project / "linked-dir" / "secret", project / ".git"]
    argv = BwrapSandbox().command(project, "true", readonly=readonly)
    assert str(secret) not in argv
    assert str(project / ".env.x") not in argv
    assert str(project / "linked-dir" / "secret") not in argv
    assert str(project / ".git") in argv


def test_project_given_through_a_symlink(project, tmp_path):
    link = tmp_path / "link"
    link.symlink_to(project)
    argv = BwrapSandbox().command(link, "true", readonly=[link / ".git"])
    assert argv[argv.index("--bind") + 1] == str(project)
    assert str(project / ".git") in argv
