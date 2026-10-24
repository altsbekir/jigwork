"""Fake OpenAI-compatible model server that replays a fixed list of tool calls.

Usage: python3 scripted_openai.py --port PORT --log LOG.jsonl --steps STEPS.json

STEPS.json is a JSON list. Each item is either [tool_name, {arguments}] or null.
The Nth request of the main Qwen Code agent (N = number of tool results already in
the conversation) gets step N as a tool call; past the end (or on null) it answers
with plain text and the session ends.

Every request is logged as one JSON line: whether it came from the main agent,
system prompt size, offered tool names, and the most recent tool result. Tests use
this log to check what Qwen Code allowed or refused.
"""

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--log", required=True)
ap.add_argument("--steps", required=True)
args = ap.parse_args()

with open(args.steps, encoding="utf-8") as f:
    STEPS = json.load(f)


def chunk(delta, finish=None):
    return {
        "id": "x",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "fake",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):  # /health and /v1/models
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            b'{"status":"ok","object":"list","data":[{"id":"qwen3.6-35b-a3b","object":"model"}]}'
        )

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        msgs = req.get("messages", [])
        system = next((m["content"] for m in msgs if m["role"] == "system"), "")
        system = system if isinstance(system, str) else json.dumps(system)
        is_main = system.startswith("You are Qwen Code")
        step_no = sum(1 for m in msgs if m["role"] == "tool")
        last_tool = next((m.get("content") for m in reversed(msgs) if m["role"] == "tool"), None)
        with open(args.log, "a", encoding="utf-8") as lf:
            lf.write(
                json.dumps(
                    {
                        "main": is_main,
                        "system_head": system[:80],
                        "system_chars": len(system),
                        "tools": sorted(t["function"]["name"] for t in req.get("tools") or []),
                        "step": step_no,
                        "last_tool_result": None if last_tool is None else str(last_tool)[:400],
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
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

        step = STEPS[step_no] if is_main and step_no < len(STEPS) else None
        if step:
            name, arguments = step
            out = [
                chunk(
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": f"call_{step_no}",
                                "type": "function",
                                "function": {"name": name, "arguments": json.dumps(arguments)},
                            }
                        ],
                    }
                ),
                chunk({}, "tool_calls"),
            ]
        else:
            out = [chunk({"role": "assistant", "content": "done"}), chunk({}, "stop")]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for c in out:
            self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")


HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
