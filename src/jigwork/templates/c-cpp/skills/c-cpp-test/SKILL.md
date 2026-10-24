---
name: c-cpp-test
description: How to write tests in tests/ for this CMake/CTest project. Use for any task that adds or changes tests, and whenever new code needs tests.
---
# Writing C / C++ tests (CTest, no framework)

- One test file per module: tests/test_<module>.c (or .cpp). Each file is its own executable.
- Register it in CMakeLists.txt:
  ```cmake
  add_executable(test_<module> tests/test_<module>.c)
  target_link_libraries(test_<module> PRIVATE core)
  add_test(NAME test_<module> COMMAND test_<module>)
  ```
- Structure: one small function per behavior, called from main(). Exit code 0 means pass.
- Use a CHECK macro that reports the failing line instead of bare assert (assert disappears with NDEBUG):
  ```c
  #include <stdio.h>
  static int failures = 0;
  #define CHECK(cond) do { if (!(cond)) { \
      fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #cond); \
      failures++; } } while (0)
  /* ... test functions ... */
  int main(void) { /* call tests */ return failures ? 1 : 0; }
  ```
- For every new public function cover a normal case, an edge case (empty, zero, boundary) and an error case.
- Compare floats with a tolerance, strings with strcmp/std::string, never pointers.
- Tests must not read or write files outside a temporary directory, and never use the network.
- In a test-only task never change source code. If the code looks wrong, report it under DOUBTS.
