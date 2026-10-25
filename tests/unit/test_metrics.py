"""The llama.cpp /metrics counters (servers/metrics.py) and the run stats (core/stats.py)."""

import http.server
import threading

import pytest

from jigwork.agents.base import AgentResult, Call, SessionStats
from jigwork.core import stats
from jigwork.core.report import Report
from jigwork.servers import metrics
from jigwork.servers.metrics import ServerCounters

# The shape llama.cpp renders (tools/server/server-task.cpp, to_metrics), shortened.
SAMPLE = """\
# HELP llamacpp:prompt_tokens_total Number of prompt tokens processed, excluding cached tokens
# TYPE llamacpp:prompt_tokens_total counter
llamacpp:prompt_tokens_total 95272
llamacpp:prompt_tokens_cached_total 441066
llamacpp:prompt_seconds_total 427.5
llamacpp:tokens_predicted_total 63180
llamacpp:tokens_predicted_seconds_total 4385
llamacpp:n_decode_total 70000
# TYPE llamacpp:predicted_tokens_seconds gauge
llamacpp:predicted_tokens_seconds 15.6
"""


def test_parse():
    counters = metrics.parse(SAMPLE)
    assert counters == ServerCounters(95272, 441066, 427.5, 63180, 4385)
    assert round(counters.generation_rate, 2) == 14.41
    assert metrics.parse("nothing here\n") is None


def test_difference_and_rates():
    before = ServerCounters(100, 0, 1.0, 1000, 50.0)
    after = ServerCounters(300, 50, 2.0, 2600, 150.0)
    delta = after.minus(before)
    assert delta == ServerCounters(200, 50, 1.0, 1600, 100.0)
    assert delta.generation_rate == 16.0 and delta.prompt_rate == 200.0
    assert ServerCounters().generation_rate is None


@pytest.fixture
def http_server():
    answers = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            code, body = answers.get(self.path, (404, ""))
            self.send_response(code)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1", answers
    server.shutdown()
    server.server_close()


def test_read(http_server):
    url, answers = http_server
    answers["/metrics"] = (200, SAMPLE)
    assert metrics.read(url).generated_tokens == 63180
    answers["/metrics"] = (501, "metrics disabled")  # llama.cpp without --metrics
    assert metrics.read(url) is None


def test_read_nothing_answers():
    assert metrics.read("http://127.0.0.1:9/v1", timeout=0.5) is None


def result(*calls, report="tool", retries=0, seconds=60.0):
    session = SessionStats(list(calls), retries, report)
    return AgentResult(True, Report(), "", seconds, 3, stats=session)


def test_record_and_summary(tmp_path):
    first = result(Call(10, 9000, 300), Call(50, 12000, 3200), report="text", retries=2)
    server = ServerCounters(500, 20000, 2.5, 3500, 200.0)
    stats.write(stats.path_for(tmp_path, "T1", 1), stats.record("T1", 1, first, server))
    stats.add_checks(stats.path_for(tmp_path, "T1", 1), False, "test failed")
    fix = result(Call(20, 15000, 800), seconds=30.0)
    stats.write(stats.path_for(tmp_path, "T1", 2), stats.record("T1", 2, fix, None))
    stats.write(stats.path_for(tmp_path, "T10", 1), stats.record("T10", 1, fix, None))
    stats.write(stats.path_for(tmp_path, "T2", 1), stats.record("T2", 1, fix, None))
    (tmp_path / "T3-attempt1.stats.json").write_text("not json")

    data = stats.load(stats.path_for(tmp_path, "T1", 1))
    assert data["kind"] == "task" and data["longest_reply"] == 3200
    assert data["output_tokens"] == 3500 and data["requests"] == 2
    assert data["server"]["generation_rate"] == 17.5
    assert data["checks"] == {"passed": False, "summary": "test failed"}
    assert stats.load(stats.path_for(tmp_path, "T1", 2))["kind"] == "fix"

    rows = stats.summarize(tmp_path)
    assert [r.task for r in rows] == ["T1", "T2", "T10"]
    t1 = rows[0]
    assert (t1.sessions, t1.seconds, t1.output_tokens, t1.longest_reply) == (2, 90.0, 4300, 3200)
    assert (t1.text_reports, t1.retries, t1.generation_rate) == (1, 2, 17.5)
    assert rows[1].generation_rate is None


def test_summary_of_a_missing_dir(tmp_path):
    assert stats.summarize(tmp_path / "nope") == []
