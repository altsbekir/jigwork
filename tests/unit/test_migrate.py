"""jigw migrate on a real v0 project, made by the v0 `yeni-proje` itself."""

import shutil
import subprocess
from datetime import datetime

import pytest

from jigwork import cli
from jigwork.commands import migrate as commands_migrate
from jigwork.core import migrate, tasks
from jigwork.core import project as project_config

from .conftest import ROOT

if shutil.which("fish") is None:
    pytest.skip("fish is needed to create a real v0 project", allow_module_level=True)


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def v0(isolated_home, monkeypatch, legacy):
    """~/Projeler/deneme as v0 left it: todo tasks, two done, one failed, logs and a patch."""
    for var in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(var, "t")
    for var in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(var, "t@example.invalid")
    subprocess.run(
        ["fish", str(ROOT / "legacy/qwen-kalip/kur.fish")], check=True, capture_output=True
    )
    (isolated_home / "Projeler").mkdir()
    subprocess.run(
        ["fish", "-c", "yeni-proje -t python deneme"],
        cwd=isolated_home / "Projeler",
        check=True,
        capture_output=True,
    )
    root = isolated_home / "Projeler/deneme"
    shutil.copy(ROOT / "legacy/qwen-kalip/ornekler/todo/docs/TASKS.md", root / "docs/TASKS.md")
    task_list = legacy.gorevleri_oku(root / "docs/TASKS.md")
    legacy.gorev_durumu_yaz(root / "docs/TASKS.md", task_list[0], "tamam")
    legacy.gorev_durumu_yaz(root / "docs/TASKS.md", task_list[1], "basarisiz")
    legacy.status_satiri(
        root, task_list[0], "tamam", 3, "8dk 16sn; lint geçti, test geçti; src/todo/model.py"
    )
    legacy.status_satiri(
        root,
        task_list[1],
        "başarısız",
        3,
        "test başarısız; yama: .kalip/calisma/T2-basarisiz-20261023-120000.patch",
    )
    (root / ".kalip/calisma/log").mkdir(parents=True)
    (root / ".kalip/calisma/log/T1-deneme1.jsonl").write_text("{}\n")
    (root / ".kalip/calisma/T2-basarisiz-20261023-120000.patch").write_text("diff\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "v0 work")
    assert git(root, "status", "--porcelain") == ""
    return root


def tree_state(root):
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git/" not in str(p.relative_to(root)) + "/"
    }


def test_plan_changes_nothing(v0, capsys):
    before = tree_state(v0)
    assert commands_migrate.run(cwd=v0) == 0
    out = capsys.readouterr().out
    assert "jigw migrate --apply" in out and "remove .kalip/" in out
    assert tree_state(v0) == before


def test_apply(v0, legacy, capsys):
    old_tasks = (v0 / "docs/TASKS.md").read_text()
    old_config = project_config.load(v0).config
    assert commands_migrate.run(apply=True, cwd=v0) == 0
    assert "git revert HEAD" in capsys.readouterr().out

    # one commit, clean tree, a v1 project with the same settings
    assert git(v0, "log", "-1", "--format=%s") == "Migrate project to jigwork v1\n"
    assert git(v0, "status", "--porcelain") == ""
    loaded = project_config.load(v0)
    assert not loaded.legacy and loaded.config == old_config
    assert 'type = "python"' in (v0 / ".jigwork/config.toml").read_text()
    assert not (v0 / ".kalip").exists()

    # TASKS.md reads the same, in English
    new_tasks = (v0 / "docs/TASKS.md").read_text()
    strip = lambda ts: [(t.id, t.status, t.type, t.files, t.task, t.acceptance) for t in ts]  # noqa: E731
    assert strip(tasks.parse(new_tasks)) == strip(tasks.parse(old_tasks))
    assert [t.status for t in tasks.parse(new_tasks)] == ["done", "failed", "pending", "pending"]
    assert not any(t.legacy for t in tasks.parse(new_tasks))
    assert (
        "## T1: Todo model and line parsing\nstatus: done\ntype: code\nfiles: src/todo/__init__.py"
        in new_tasks
    )
    assert '"status": pending | done | failed | skip' in new_tasks  # the v1 rules comment
    assert "durum" not in new_tasks and "Görev" not in new_tasks

    # STATUS.md
    status = (v0 / "docs/STATUS.md").read_text()
    assert "| Date | Task | Result | Attempts | Note |" in status and "Tarih" not in status
    row = "| T1 Todo model and line parsing | done | 3 | 8m 16s; lint passed, test passed; "
    assert row + "src/todo/model.py |" in status
    assert (
        "| failed | 3 | test failed; patch: .jigwork/work/T2-basarisiz-20261023-120000.patch |"
        in status
    )
    assert "jigwork adds a row after every task" in status

    # ARCHITECTURE.md comments, .gitignore, the work dir
    arch = (v0 / "docs/ARCHITECTURE.md").read_text()
    assert "Fill this in when the project starts" in arch and not migrate.COMMENT.search(
        arch
    ).group().count("ü")
    gitignore = (v0 / ".gitignore").read_text().splitlines()
    assert (
        ".jigwork/work/" in gitignore
        and ".kalip/calisma/" not in gitignore
        and "# jigwork (python)" in gitignore
    )
    assert (v0 / ".jigwork/work/log/T1-deneme1.jsonl").exists()
    assert (v0 / ".jigwork/work/T2-basarisiz-20261023-120000.patch").exists()
    assert tasks.lint(new_tasks)[1] == []

    # untouched
    assert (v0 / "AGENTS.md").read_text().startswith("# Project: deneme")
    assert (v0 / ".qwen/skills/python-code/SKILL.md").exists()


def test_new_status_rows_after_migration_are_english(v0):
    from jigwork.core.status import append_row

    commands_migrate.run(apply=True, cwd=v0)
    task = tasks.load(v0 / "docs/TASKS.md")[2]
    append_row(v0 / "docs/STATUS.md", task, "done", 1, "1m 05s", when=datetime(2026, 10, 24, 12, 0))
    assert (
        (v0 / "docs/STATUS.md")
        .read_text()
        .rstrip()
        .endswith("| T3 Operations on the list | done | 1 | 1m 05s |")
    )


def test_user_edited_comments_are_left_alone(v0):
    text = (
        (v0 / "docs/ARCHITECTURE.md")
        .read_text()
        .replace(
            "<!-- 2-3 cümle: program ne yapıyor, kim kullanıyor -->",
            "<!-- benim notum: dokunma -->",
        )
    )
    (v0 / "docs/ARCHITECTURE.md").write_text(text)
    with (v0 / "docs/TASKS.md").open("a") as f:
        f.write("\n<!-- not: durum: bekliyor -->\n")
    git(v0, "commit", "-qam", "notes")
    commands_migrate.run(apply=True, cwd=v0)
    assert "<!-- benim notum: dokunma -->" in (v0 / "docs/ARCHITECTURE.md").read_text()
    assert "<!-- not: durum: bekliyor -->" in (v0 / "docs/TASKS.md").read_text()


@pytest.mark.parametrize(
    ("setup", "key"),
    [
        (lambda root: (root / "src/wip.py").write_text(""), "migrate.dirty"),
        (
            lambda root: (root / ".kalip/calisma/yarim.json").write_text(
                '{"gorev": "T3", "deneme": 1}'
            ),
            "migrate.resume_pending",
        ),
    ],
)
def test_refusals(v0, setup, key):
    setup(v0)
    with pytest.raises(migrate.MigrateError) as error:
        migrate.plan(v0)
    assert error.value.key == key


def test_twice_and_not_v0(v0, tmp_path):
    commands_migrate.run(apply=True, cwd=v0)
    with pytest.raises(migrate.MigrateError) as error:
        migrate.plan(v0)
    assert error.value.key == "migrate.already"
    plain = tmp_path / "plain"
    plain.mkdir()
    subprocess.run(["git", "init", "-q", str(plain)], check=True)
    with pytest.raises(migrate.MigrateError) as error:
        migrate.plan(plain)
    assert error.value.key == "migrate.not_v0"


def test_a_tasks_rewrite_that_reads_differently_is_never_written(v0, monkeypatch):
    before = tree_state(v0)
    monkeypatch.setattr(migrate, "rewrite_tasks", lambda text: text.replace("kabul:", "notes:", 1))
    with pytest.raises(migrate.MigrateError) as error:
        migrate.plan(v0)
    assert error.value.key == "migrate.tasks_differ"
    assert tree_state(v0) == before


@pytest.mark.parametrize(
    ("note", "expected"),
    [
        (
            "5dk 01sn; lint geçti, test geçti; src/a.py",
            "5m 01s; lint passed, test passed; src/a.py",
        ),
        ("45sn; kontrol yok; x.py", "45s; no checks; x.py"),
        (
            "Qwen hiçbir dosyayı değiştirmedi (şüpheler: belirsiz); yama: .kalip/calisma/T1.patch",
            "the agent changed no files (doubts: belirsiz); patch: .jigwork/work/T1.patch",
        ),
        ("elle yazdığım not", "elle yazdığım not"),
    ],
)
def test_status_note_rules(note, expected):
    row = f"| 2026-10-23 12:00 | T1 x | tamam | 1 | {note} |\n"
    assert migrate.rewrite_status(row) == f"| 2026-10-23 12:00 | T1 x | done | 1 | {expected} |\n"


def test_cli(monkeypatch):
    seen = []
    monkeypatch.setattr(commands_migrate, "run", lambda apply=False: seen.append(apply) or 0)
    assert cli.main(["migrate"]) == 0 and cli.main(["migrate", "--apply"]) == 0
    assert seen == [False, True]
