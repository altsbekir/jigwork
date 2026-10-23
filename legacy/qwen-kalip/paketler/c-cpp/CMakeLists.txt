cmake_minimum_required(VERSION 3.24)
project({{PROJE_ADI}} LANGUAGES C CXX)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

add_compile_options(-Wall -Wextra -Wpedantic)

enable_testing()

# --- Kod buraya eklenecek (görevlerle) ---
# Uygulama kodu bir kütüphane olarak derlenir ki testler ona bağlanabilsin:
#   add_library(core src/foo.c)
#   target_include_directories(core PUBLIC include)
#
# Programın kendisi:
#   add_executable(app src/main.c)
#   target_link_libraries(app PRIVATE core)
#
# Her test ayrı bir çalıştırılabilir dosya:
#   add_executable(test_foo tests/test_foo.c)
#   target_link_libraries(test_foo PRIVATE core)
#   add_test(NAME test_foo COMMAND test_foo)
