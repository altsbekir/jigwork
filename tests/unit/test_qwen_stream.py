import json

import pytest

from jigwork.agents.base import Event, Limits
from jigwork.agents.qwen_code import QwenCode
from jigwork.agents.qwen_code.stream import StreamReader
from jigwork.core.report import Report

from .conftest import FAKE_QWEN


def assistant(*parts):
    return json.dumps({"type": "assistant", "message": {"content": list(parts)}})


def tool(name, **args):
    return {"type": "tool_use", "name": name, "input": args}


def text(value):
    return {"type": "text", "text": value}


STRUCTURED = {"changed": ["a.py"], "done": "Did it.", "needs": ["none"], "doubts": "none"}


def feed(project, *lines, returncode=0):
    reader = StreamReader(project)
    events = []
    for line in lines:
        events += reader.feed(line, 1.0)
    return events, reader.finish(returncode, 2.0)


def test_tool_calls_become_events(tmp_path):
    events, result = feed(
        tmp_path,
        json.dumps({"type": "system", "subtype": "init", "tools": ["read_file"]}),
        assistant(tool("read_file", file_path=str(tmp_path / "src/a.py")), text("thinking aloud")),
        assistant(tool("glob", pattern="**/*.py"), tool("list_directory", path="/elsewhere")),
        assistant(tool("structured_output", **STRUCTURED)),
        json.dumps({"type": "result", "subtype": "success", "structured_result": STRUCTURED}),
    )
    assert events == [
        Event("read_file", "src/a.py", 1.0),
        Event("glob", "**/*.py", 1.0),
        Event("list_directory", "/elsewhere", 1.0),
    ]
    assert result.tool_calls == 4
    assert result.ok and result.error == ""
    assert result.report == Report(changed=["a.py"], done="Did it.")
    assert result.seconds == 2.0


def test_success_without_structured_result_parses_text(tmp_path):
    _, result = feed(
        tmp_path,
        assistant(text("CHANGED: b.py\nDONE: ok")),
        json.dumps({"type": "result", "subtype": "success", "result": "CHANGED: a.py\nDONE: fine"}),
    )
    assert result.ok and result.report.changed == ["a.py"] and result.report.done == "fine"


def test_plain_text_instead_of_structured_output_is_parsed(tmp_path):
    _, result = feed(
        tmp_path,
        assistant(text("CHANGED: a.py\nDONE: did\nNEEDS: pip install x\nDOUBTS: none")),
        json.dumps(
            {
                "type": "result",
                "subtype": "error_during_execution",
                "error": {
                    "message": "Model produced plain text instead of calling the "
                    "structured_output tool"
                },
            }
        ),
        returncode=1,
    )
    assert result.ok
    assert result.report.needs == ["pip install x"]


def test_other_errors_are_reported(tmp_path):
    _, result = feed(
        tmp_path,
        assistant(text("partial")),
        json.dumps(
            {"type": "result", "subtype": "error_during_execution", "error": {"message": "boom"}}
        ),
        returncode=1,
    )
    assert (result.ok, result.error) == (False, "boom")


def test_limit_exit_code_wins(tmp_path):
    _, result = feed(
        tmp_path,
        json.dumps({"type": "result", "subtype": "success", "structured_result": STRUCTURED}),
        returncode=55,
    )
    assert (result.ok, result.error) == (False, "limit")


def test_no_result_line_reports_exit_code(tmp_path):
    _, result = feed(tmp_path, "not json at all", "[1, 2]", '"str"', returncode=3)
    assert (result.ok, result.error) == (False, "exit:3")


def test_malformed_events_are_ignored(tmp_path):
    events, result = feed(
        tmp_path,
        json.dumps({"type": "assistant"}),
        json.dumps({"type": "assistant", "message": {"content": ["x", {"type": "tool_use"}]}}),
    )
    assert events == [Event("None", "", 1.0)]
    assert result.tool_calls == 1


# --- run_task with a fake qwen executable ------------------------------------------------------


def test_run_task_argv_log_and_events(tmp_path, fake_qwen):
    project = tmp_path / "proj"
    project.mkdir()
    argv_file = fake_qwen(
        lines=[
            assistant(tool("write_file", file_path=str(project / "a.py"))),
            {"type": "result", "subtype": "success", "structured_result": STRUCTURED},
        ]
    )
    log = project / ".jigwork/work/log/T1-attempt1.jsonl"
    seen = []
    result = QwenCode(executable=str(FAKE_QWEN)).run_task(
        project, "## Task T1: x", Limits("10m", 7), log, seen.append
    )
    record = json.loads(argv_file.read_text())
    assert record["cwd"] == str(project)
    schema = log.parent / "report-schema.json"
    assert record["argv"] == [
        "## Task T1: x",
        "--approval-mode", "auto-edit",
        "--output-format", "stream-json",
        "--json-schema", f"@{schema}",
        "--max-wall-time", "10m",
        "--max-tool-calls", "7",
    ]  # fmt: skip
    assert json.loads(schema.read_text())["required"] == ["changed", "done", "needs", "doubts"]
    assert [e.name for e in seen] == ["write_file"] and seen[0].target == "a.py"
    assert result.ok and result.report.changed == ["a.py"]
    lines = log.read_text().splitlines()
    assert json.loads(lines[0]) == {"prompt": "## Task T1: x"}
    assert len(lines) == 3


def test_run_task_nonzero_exit(tmp_path, fake_qwen):
    fake_qwen(lines=["garbage"], exit=55)
    result = QwenCode(executable=str(FAKE_QWEN)).run_task(
        tmp_path, "p", Limits(), tmp_path / "log/x.jsonl", lambda e: None
    )
    assert (result.ok, result.error) == (False, "limit")


def test_run_task_kills_agent_when_interrupted(tmp_path, fake_qwen):
    fake_qwen(lines=[assistant(tool("read_file", file_path="a"))], sleep=30)

    def interrupt(_event):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        QwenCode(executable=str(FAKE_QWEN)).run_task(
            tmp_path, "p", Limits(), tmp_path / "log/x.jsonl", interrupt
        )


@pytest.mark.parametrize(
    ("args", "refused"),
    [
        (["--yolo"], ["--yolo"]),
        (["-y"], ["-y"]),
        (["--approval-mode", "yolo"], ["yolo"]),
        (["--approval-mode=YOLO"], ["--approval-mode=YOLO"]),
        (["--approval-mode", "auto-edit", "-c"], []),
        ([], []),
    ],
)
def test_refused_args(args, refused):
    assert QwenCode.refused_args(args) == refused


# Verified on Qwen Code 0.26.0 against a closed port (see agents/qwen_code/stream.py)
REFUSED = "[API Error: Connection error. (cause: connect ECONNREFUSED 127.0.0.1:32863)]"


def test_connection_error_is_recognised(tmp_path):
    _, result = feed(
        tmp_path,
        assistant(text(REFUSED)),  # the error also arrives as assistant text...
        json.dumps(
            {"type": "result", "subtype": "error_during_execution", "error": {"message": REFUSED}}
        ),
        returncode=1,
    )
    assert (result.ok, result.connection_error) == (False, True)
    assert result.report == Report()  # ...and is not taken for a plain-text report


@pytest.mark.parametrize("message", ["boom", "Model produced plain text", "limit"])
def test_other_errors_are_not_connection_errors(tmp_path, message):
    _, result = feed(
        tmp_path,
        json.dumps(
            {"type": "result", "subtype": "error_during_execution", "error": {"message": message}}
        ),
        returncode=1,
    )
    assert not result.connection_error


# --- session stats (shapes verified on 0.26.0 logs of the phase-1 bench run) ----------------


def usage_message(parts, input_tokens, output_tokens, cached=0):
    usage = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": cached,
        "total_tokens": input_tokens + output_tokens,
    }
    return json.dumps({"type": "assistant", "message": {"content": parts, "usage": usage}})


def test_stats_per_request_retries_and_report_source(tmp_path):
    reader = StreamReader(tmp_path)
    lines = [
        (usage_message([{"type": "thinking", "thinking": "hm"}], 0, 0), 5.0),  # zeros: skipped
        (usage_message([tool("read_file", file_path="a.py")], 8934, 271, 6444), 12.0),
        (json.dumps({"type": "system", "subtype": "retry", "data": {"reason": "retry"}}), 13.0),
        (usage_message([tool("structured_output", **STRUCTURED)], 11546, 1443, 9204), 90.0),
        (
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "structured_result": STRUCTURED,
                    "usage": {"input_tokens": 20480, "output_tokens": 2014},
                }
            ),
            91.0,
        ),
    ]
    for line, seconds in lines:
        reader.feed(line, seconds)
    stats = reader.finish(0, 91.0).stats
    assert [(c.seconds, c.input_tokens, c.output_tokens, c.cached_tokens) for c in stats.calls] == [
        (12.0, 8934, 271, 6444),
        (90.0, 11546, 1443, 9204),
    ]
    assert stats.retries == 1 and stats.report_source == "tool"
    assert stats.longest_reply == 1443
    assert (stats.input_tokens, stats.output_tokens) == (20480, 2014)  # retried requests too


def test_stats_mark_the_plain_text_fallback(tmp_path):
    _, result = feed(
        tmp_path,
        assistant(text("CHANGED: a.py\nDONE: did\nNEEDS: none\nDOUBTS: none")),
        json.dumps(
            {
                "type": "result",
                "subtype": "error_during_execution",
                "error": {"message": "plain text instead of calling the structured_output tool"},
            }
        ),
        returncode=1,
    )
    assert result.stats.report_source == "text"
    assert result.stats.calls == [] and result.stats.longest_reply == 0


def test_stats_ignore_odd_usage(tmp_path):
    reader = StreamReader(tmp_path)
    reader.feed(json.dumps({"type": "assistant", "message": {"content": [], "usage": "x"}}), 1)
    bad = {"input_tokens": -1, "output_tokens": "7"}
    reader.feed(json.dumps({"type": "assistant", "message": {"content": [], "usage": bad}}), 2)
    assert reader.finish(0, 3).stats.calls == []
