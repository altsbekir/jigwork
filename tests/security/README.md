# Security tests

`test_bwrap_box.py` runs escape probes inside the real bubblewrap check box. Every probe also
runs in a box with that one protection removed and must then report the leak, so a probe that
cannot see a broken box fails the suite ("unsafe must fail").

The fake HOME lives in `/var/tmp` (not `/tmp`), otherwise the `/tmp` tmpfs would hide it and the
HOME probes would prove nothing. Network is probed against a listener on the host's loopback, so
the result does not depend on internet access. Needs Linux, `bwrap` and `/usr/bin/python3`.

The Qwen Code probes (tools, writes outside the project, protected files) are still in
`tests/legacy/security_probes.sh` and move here with `agents/qwen_code/` (roadmap step 6).
