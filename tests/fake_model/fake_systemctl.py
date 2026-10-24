#!/usr/bin/env python3
"""Stand-in for `systemctl` and `journalctl` in every test (tests/conftest.py puts it first on
PATH), so no test can start, stop or inspect the real user services.

State lives in $FAKE_SYSTEMD_DIR: `exists` (the unit is installed), `active`, `start-fails`,
`invocation` (a new id on every start, like systemd's InvocationID); every call is appended to
`calls.log`.
"""

import os
import sys
import uuid
from pathlib import Path

state = Path(os.environ["FAKE_SYSTEMD_DIR"])
state.mkdir(parents=True, exist_ok=True)
args = [a for a in sys.argv[1:] if a not in ("--user", "--quiet", "--no-pager")]
with open(state / "calls.log", "a") as log:
    log.write(Path(sys.argv[0]).name + " " + " ".join(sys.argv[1:]) + "\n")

if Path(sys.argv[0]).name == "journalctl":
    print("fake journal")
    sys.exit(0)

command = args[0] if args else ""
if command == "cat":
    sys.exit(0 if (state / "exists").exists() else 1)
if command == "is-active":
    sys.exit(0 if (state / "active").exists() else 3)
if command in ("start", "restart"):
    if (state / "start-fails").exists() or not (state / "exists").exists():
        sys.exit(1)
    if command == "restart" or not (state / "active").exists():
        (state / "invocation").write_text(uuid.uuid4().hex)
    (state / "active").touch()
    sys.exit(0)
if command == "stop":
    (state / "active").unlink(missing_ok=True)
    (state / "invocation").unlink(missing_ok=True)
    sys.exit(0)
if command == "show":
    invocation = state / "invocation"
    print(invocation.read_text() if invocation.exists() else "")
    sys.exit(0)
sys.exit(0)  # daemon-reload and anything else
