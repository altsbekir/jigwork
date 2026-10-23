---
name: c-cpp-code
description: Conventions for writing or editing C/C++ sources and headers in src/ and include/. Use for any task that changes .c, .h, .cpp or .hpp files outside tests/.
---
# C / C++ code conventions

- Follow the language the project uses (see Decisions in docs/ARCHITECTURE.md). Do not mix C and C++ in one module.
- Every .c/.cpp in src/ has a matching header in include/ with an include guard (`#pragma once` is fine).
- When you add a source file, also add it to the right target in CMakeLists.txt.
- Code must compile cleanly with -Wall -Wextra -Wpedantic; warnings are errors.
- Check every return value that can fail (malloc, fopen, ...). Every allocation has exactly one clear owner that frees it.
- No global mutable state unless docs/ARCHITECTURE.md allows it.
- Use `size_t` for sizes and indexes; never compare signed and unsigned.
- Bounds-check every buffer write. Prefer snprintf over sprintf, never use gets/strcpy/strcat.
- C++: RAII, std::string/std::vector/std::unique_ptr instead of raw new/delete; pass large objects by const reference.
- Small functions with one job. Keep I/O at the edges; core logic is pure functions that tests can call.
