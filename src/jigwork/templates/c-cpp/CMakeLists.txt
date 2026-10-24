cmake_minimum_required(VERSION 3.24)
project({{PROJECT_NAME}} LANGUAGES C CXX)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

add_compile_options(-Wall -Wextra -Wpedantic)

enable_testing()

# --- Code goes here (added by tasks) ---
# The application code is built as a library so the tests can link to it:
#   add_library(core src/foo.c)
#   target_include_directories(core PUBLIC include)
#
# The program itself:
#   add_executable(app src/main.c)
#   target_link_libraries(app PRIVATE core)
#
# Every test is its own executable:
#   add_executable(test_foo tests/test_foo.c)
#   target_link_libraries(test_foo PRIVATE core)
#   add_test(NAME test_foo COMMAND test_foo)
