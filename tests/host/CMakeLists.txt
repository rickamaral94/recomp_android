# SPDX-License-Identifier: GPL-3.0-or-later

add_executable(recomp_common_tests
    test_main.cpp
    test_json.cpp
    test_report.cpp
    test_vulkan_probe.cpp
)
target_link_libraries(recomp_common_tests PRIVATE recomp_common)
target_compile_options(recomp_common_tests PRIVATE -Wall -Wextra -Werror)
add_test(NAME recomp_common_tests COMMAND recomp_common_tests)

# Prints the host's report.json; the test below checks that it is valid JSON with the schema keys.
add_executable(recomp-report report_cli.cpp)
target_link_libraries(recomp-report PRIVATE recomp_common)
target_compile_options(recomp-report PRIVATE -Wall -Wextra -Werror)

find_package(Python3 COMPONENTS Interpreter)
if(Python3_FOUND)
    add_test(NAME report_cli_schema
        COMMAND ${CMAKE_COMMAND}
            -DCLI=$<TARGET_FILE:recomp-report>
            -DPYTHON=${Python3_EXECUTABLE}
            -DCHECKER=${PROJECT_SOURCE_DIR}/tools/check_report.py
            -P ${CMAKE_CURRENT_SOURCE_DIR}/run_report_check.cmake)
endif()

if(Python3_FOUND)
    add_test(NAME tools_ps3_inventory
        COMMAND ${Python3_EXECUTABLE} -I ${PROJECT_SOURCE_DIR}/tests/tools/test_ps3_inventory.py)
endif()
