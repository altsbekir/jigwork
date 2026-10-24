import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from jigwork.servers import health
from jigwork.servers.health import Probe, probe

from ..fake_model.server import free_port


@pytest.fixture
def fake_server():
    """A local HTTP server whose answers each test sets in `routes` (path -> (status, body))."""
    routes: dict[str, tuple[int, bytes]] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            status, body = routes.get(self.path, (404, b"not found"))
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1", routes
    server.shutdown()
    server.server_close()


PROPS = {
    "default_generation_settings": {"n_ctx": 65536},
    "total_slots": 1,
    "model_alias": "qwen3.6-35b-a3b",
}


def test_llama_cpp_ready_with_settings(fake_server):
    url, routes = fake_server
    routes["/health"] = (200, b'{"status":"ok"}')
    routes["/props"] = (200, json.dumps(PROPS).encode())
    assert probe(url) == Probe(health.READY, context=65536, slots=1, model="qwen3.6-35b-a3b")
    assert health.is_healthy(url)


def test_llama_cpp_loading(fake_server):
    url, routes = fake_server
    routes["/health"] = (503, b'{"error":{"message":"Loading model","code":503}}')
    assert probe(url).state == health.LOADING
    assert not health.is_healthy(url)


def test_ready_without_props(fake_server):
    url, routes = fake_server
    routes["/health"] = (200, b'{"status":"ok"}')  # e.g. --no-endpoint-props
    assert probe(url) == Probe(health.READY)


def test_other_openai_server_without_health(fake_server):
    url, routes = fake_server
    routes["/v1/models"] = (200, b'{"data":[]}')
    assert probe(url) == Probe(health.READY)


def test_something_else_answers(fake_server):
    url, routes = fake_server
    routes["/health"] = (500, b"boom")
    assert probe(url).state == health.ERROR
    routes.pop("/health")
    assert probe(url).state == health.ERROR  # 404 and no /v1/models either


def test_nothing_listens():
    assert probe(f"http://127.0.0.1:{free_port()}/v1").state == health.DOWN


def test_urls():
    assert health.health_url("http://h:1/v1") == "http://h:1/health"
    assert health.health_url("http://h:1/v1/") == "http://h:1/health"
    assert health.root_url("http://h:1") == "http://h:1"
