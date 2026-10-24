"""Command-line entry point: argument parsing only; work happens in the modules it calls."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from jigwork import COMMAND, __version__, i18n, user_config
from jigwork.commands import chat as commands_chat
from jigwork.commands import run as commands_run
from jigwork.commands import setup as commands_setup
from jigwork.core import tasks
from jigwork.i18n import t


class _HelpFormatter(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        super().add_usage(
            usage, actions, groups, prefix=t("cli.usage") if prefix is None else prefix
        )


class _Parser(argparse.ArgumentParser):
    """ArgumentParser with translated help chrome. argparse's own error texts stay English."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("formatter_class", _HelpFormatter)
        kwargs.setdefault("add_help", False)
        super().__init__(*args, **kwargs)
        self._positionals.title = t("cli.positionals")
        self._optionals.title = t("cli.options")
        self.add_argument("-h", "--help", action="help", help=t("cli.help"))

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(2, t("cli.error", prog=self.prog, message=message) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog=COMMAND, description=t("cli.description"))
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}", help=t("cli.version")
    )
    commands = parser.add_subparsers(
        dest="command",
        metavar=t("cli.command_metavar"),
        title=t("cli.commands"),
        parser_class=_Parser,
    )

    lang = commands.add_parser("lang", help=t("lang.help"), description=t("lang.help"))
    lang.add_argument("lang", nargs="?", choices=[*i18n.SUPPORTED, "auto"], help=t("lang.arg"))
    lang.set_defaults(func=cmd_lang)

    tasks_parser = commands.add_parser("tasks", help=t("tasks.help"), description=t("tasks.help"))
    tasks_commands = tasks_parser.add_subparsers(
        dest="tasks_command",
        metavar=t("cli.command_metavar"),
        title=t("cli.commands"),
        parser_class=_Parser,
    )
    tasks_parser.set_defaults(func=lambda _args: _usage(tasks_parser))
    lint = tasks_commands.add_parser(
        "lint", help=t("tasks.lint_help"), description=t("tasks.lint_help")
    )
    lint.add_argument(
        "path", nargs="?", type=Path, default=Path("docs/TASKS.md"), help=t("tasks.path")
    )
    lint.set_defaults(func=cmd_tasks_lint)

    run = commands.add_parser("run", help=t("run.help"), description=t("run.help"))
    run.add_argument("--one", action="store_true", help=t("run.one"))
    run.set_defaults(func=lambda args: commands_run.run("run", one=args.one))
    for name in ("resume", "check", "status"):
        sub = commands.add_parser(
            name, help=t(f"run.{name}_help"), description=t(f"run.{name}_help")
        )
        sub.set_defaults(func=lambda _args, name=name: commands_run.run(name))

    chat = commands.add_parser("chat", help=t("chat.help"), description=t("chat.help"))
    chat.add_argument("args", nargs=argparse.REMAINDER, help=t("chat.args"))
    chat.set_defaults(func=lambda args: commands_chat.run(args.args))

    setup = commands.add_parser("setup", help=t("setup.help"), description=t("setup.help"))
    setup.set_defaults(func=lambda _args: commands_setup.run())
    return parser


def _usage(parser: argparse.ArgumentParser) -> int:
    parser.print_help(sys.stderr)
    return 2


def _describe(selection: i18n.Selection) -> str:
    if selection.source == "env":
        return t("lang.source_env", var=i18n.ENV_VAR)
    if selection.source == "config":
        return t("lang.source_config", path=selection.detail)
    if selection.source == "locale":
        return t("lang.source_locale", detail=selection.detail)
    return t("lang.source_default")


def cmd_lang(args: argparse.Namespace) -> int:
    if args.lang is None:
        selection = i18n.active()
        print(
            t("lang.current", name=i18n.NATIVE_NAMES[selection.lang], source=_describe(selection))
        )
        return 0

    try:
        path = user_config.set_value(i18n.CONFIG_KEY, None if args.lang == "auto" else args.lang)
    except user_config.ConfigError as exc:
        print(t("config.unreadable", path=exc.path, error=exc.error), file=sys.stderr)
        return 1
    i18n.reset()
    if args.lang == "auto":
        print(t("lang.auto", name=i18n.NATIVE_NAMES[i18n.active().lang]))
    else:
        print(t("lang.saved", name=i18n.NATIVE_NAMES[args.lang], path=path))
    if i18n.normalize(os.environ.get(i18n.ENV_VAR)):
        print(t("lang.env_overrides", var=i18n.ENV_VAR, value=os.environ[i18n.ENV_VAR]))
    return 0


def cmd_tasks_lint(args: argparse.Namespace) -> int:
    try:
        text = args.path.read_text(encoding="utf-8")
    except OSError as exc:
        print(t("tasks.unreadable", path=args.path, error=exc.strerror or exc), file=sys.stderr)
        return 1
    found, issues = tasks.lint(text)
    for issue in issues:
        where = f"{args.path}:{issue.line}: " + (f"{issue.task_id}: " if issue.task_id else "")
        severity = t(f"tasks.severity_{issue.severity}")
        print(where + severity + ": " + t(f"tasks.lint.{issue.code}", **issue.fields))
    errors = sum(i.severity == "error" for i in issues)
    print(t("tasks.summary", tasks=len(found), errors=errors, warnings=len(issues) - errors))
    return 1 if errors else 0


def _chat_passthrough(argv: list[str]) -> list[str] | None:
    """`jigw chat ARGS...`: ARGS go to the agent untouched (argparse would reject `-c`)."""
    if not argv or argv[0] != "chat" or argv[1:] in (["-h"], ["--help"]):
        return None
    rest = argv[1:]
    return rest[1:] if rest[:1] == ["--"] else rest


def main(argv: Sequence[str] | None = None) -> int:
    i18n.reset()
    argv = list(sys.argv[1:] if argv is None else argv)
    if (chat_args := _chat_passthrough(argv)) is not None:
        return commands_chat.run(chat_args)
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        return _usage(parser)
    return args.func(args)
