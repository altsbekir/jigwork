# Security tests

`test_bwrap_box.py` runs escape probes inside the real bubblewrap check box. Every probe also
runs in a box with that one protection removed and must then report the leak, so a probe that
cannot see a broken box fails the suite ("unsafe must fail").

The fake HOME lives in `/var/tmp` (not `/tmp`), otherwise the `/tmp` tmpfs would hide it and the
HOME probes would prove nothing. Network is probed against a listener on the host's loopback, so
the result does not depend on internet access. Needs Linux, `bwrap` and `/usr/bin/python3`.

`test_qwen_code.py` runs the real `qwen` CLI with the settings jigwork writes against a scripted
fake model (`tests/fake_model/`), in yolo mode, trying every escape route found so far. The same
run with the protections stripped must report exactly the known leaks. Two more runs check that
a hostile project `.qwen/settings.json` and user-level `permissions.allow` rules change nothing.
Needs `qwen`, `bwrap`, `git`; `JIGWORK_NO_QWEN=1` skips it (for machines without Qwen Code).
