---
name: fix-failing-checks
description: Use when lint, build or test output shows failures after a change. How to read the errors and make the smallest correct fix.
---
# Fixing failing checks

You receive the output of lint/build/test commands that failed after a change.

1. Read the FIRST error fully. Note the file, the line and the error type.
2. Open that file around that line. Find the real cause; do not patch the symptom.
3. Decide which side is wrong:
   - The code is wrong: fix the code.
   - The test contradicts the task's acceptance criteria: fix the test and explain why under DOUBTS.
   - In every other case, never weaken, skip or delete a test to make it pass.
4. Make the smallest change that fixes that error. Do not touch unrelated code.
5. Several errors often share one cause. Check that before editing each one separately.
6. If the same error survives two attempts, stop and explain under DOUBTS what you think is wrong.

Forbidden shortcuts:
- silencing the checker (`# noqa`, `# type: ignore`, `#pragma` warning disables)
- skipping tests (`pytest.skip`, `xfail`, commenting a test out)
- catching and ignoring errors (`except Exception: pass`, empty catch blocks)
- hardcoding the value a test expects
