"""A scripted OpenAI-compatible model server, run in a thread (for doctor and the tests).

`steps` is a list; each item is [tool_name, {arguments}] or None. The Nth request of the main
Qwen Code agent (N = tool results already in the conversation) gets step N as a tool call;
past the end, or on None, it answers with plain text and the session ends. Every request is
recorded: whether it came from the main agent, the offered tool names, the sampling values.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REAL_SERVER_PORT = 8091  # never used here: the real model server's default port


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    if port == REAL_SERVER_PORT:
        return free_port()
    return port


def _chunk(delta: dict, finish: str | None = None) -> dict:
    return {
        "id": "x",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "fake",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


class ScriptedModel:
    def __init__(self, steps: list, model_id: str = "qwen3.6-35b-a3b") -> None:
        self.steps = steps
        self.model_id = model_id
        self.requests: list[dict] = []
        self.port = free_port()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def _handler(self):
        model = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):  # /health, /v1/models
                body = {
                    "status": "ok",
                    "object": "list",
                    "data": [{"id": model.model_id, "object": "model"}],
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())

            def do_POST(self):
                req = json.loads(
                    self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}"
                )
                messages = req.get("messages", [])
                system = next((m["content"] for m in messages if m["role"] == "system"), "")
                system = system if isinstance(system, str) else json.dumps(system)
                main = system.startswith("You are Qwen Code")
                step_no = sum(1 for m in messages if m["role"] == "tool")
                model.requests.append(
                    {
                        "main": main,
                        "system_head": system[:80],
                        "tools": sorted(t["function"]["name"] for t in req.get("tools") or []),
                        "step": step_no,
                        "sampling": {
                            k: req.get(k)
                            for k in (
                                "temperature",
                                "top_p",
                                "top_k",
                                "min_p",
                                "presence_penalty",
                                "max_tokens",
                            )
                        },
                    }
                )
                step = model.steps[step_no] if main and step_no < len(model.steps) else None
                if step:
                    name, arguments = step
                    function = {"name": name, "arguments": json.dumps(arguments)}
                    call = {
                        "index": 0,
                        "id": f"call_{step_no}",
                        "type": "function",
                        "function": function,
                    }
                    out = [
                        _chunk({"role": "assistant", "tool_calls": [call]}),
                        _chunk({}, "tool_calls"),
                    ]
                else:
                    out = [_chunk({"role": "assistant", "content": "done"}), _chunk({}, "stop")]
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for c in out:
                    self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")

        return Handler

    def __enter__(self) -> ScriptedModel:
        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        assert self._server is not None and self._thread is not None
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
