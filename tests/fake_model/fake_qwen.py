#!/usr/bin/env python3
"""A stand-in for the `qwen` CLI, for unit tests that need no real agent.

Reads a JSON scenario from $FAKE_QWEN_SCENARIO: {"argv_file": path, "lines": [str or object],
"append": {path: text}, "exit": code, "sleep": seconds}. Records its argv, appends text to
files (e.g. to tamper with .git/config), prints the lines, and exits with the code.
"""

import json
import os
import sys
import time

scenario = json.load(open(os.environ["FAKE_QWEN_SCENARIO"], encoding="utf-8"))
if scenario.get("argv_file"):
    with open(scenario["argv_file"], "w", encoding="utf-8") as f:
        json.dump({"argv": sys.argv[1:], "cwd": os.getcwd()}, f)
for path, text in scenario.get("append", {}).items():
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)
for line in scenario.get("lines", []):
    print(line if isinstance(line, str) else json.dumps(line), flush=True)
time.sleep(scenario.get("sleep", 0))
sys.exit(scenario.get("exit", 0))
