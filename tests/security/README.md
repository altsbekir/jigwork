# Security tests

The escape probes live in the package (`jigwork/doctor/agent_probe.py`, `box_probe.py`), so
`jigw doctor` runs exactly what these tests run, on the user's machine with the user's settings.

- `test_bwrap_box.py`: the check box. Every probe also runs in a box with that one protection
  removed and must then report the leak ("unsafe must fail"). The fake HOME lives in `/var/tmp`
  (not `/tmp`), otherwise the `/tmp` tmpfs would hide it and the HOME probes would prove nothing.
  Network is probed against a listener on the host's loopback, so the result does not depend on
  internet access. Needs Linux, `bwrap` and `/usr/bin/python3`.
- `test_qwen_code.py`: the real `qwen` CLI with jigwork's settings against a scripted fake model
  (`jigwork/doctor/fake_model.py`), in yolo mode. With the protections stripped the probes must
  report exactly the known leaks. A hostile project `.qwen/settings.json`, user-level
  `permissions.allow` rules and configured MCP servers change nothing.
- `test_doctor_live.py`: `jigw doctor` passes on a protected setup and fails (exit code 1) on an
  unprotected one (docs/architecture.md, security invariant 6).

Needs `qwen`, `bwrap`, `git`; `JIGWORK_NO_QWEN=1` skips the Qwen Code parts.
