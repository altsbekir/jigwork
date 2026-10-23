---
name: python-test
description: How to write pytest tests in tests/. Use for any task that adds or changes tests, and whenever new code needs tests.
---
# Writing pytest tests

- One file per module: tests/test_<module>.py. Test names: test_<behavior>_<condition>.
- One behavior per test. Arrange, act, assert, separated by blank lines.
- For every new public function cover at least:
  1. a normal case
  2. an edge case (empty input, zero, boundary value)
  3. an error case, with `with pytest.raises(SomeError):`
- Use `tmp_path` for files and `monkeypatch` for environment variables or time.
  Never touch real user files, the network or a real database.
- Use `@pytest.mark.parametrize` instead of copy-pasted tests.
- Assert concrete values. `assert result is not None` alone proves nothing.
- Tests must not depend on each other or on run order.
- Test private helpers (names starting with `_`) only through the public function.
- In a test-only task never change source code. If the code looks wrong, report it under DOUBTS.
