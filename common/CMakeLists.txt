# SPDX-License-Identifier: GPL-3.0-or-later
#
# recomp_common: services shared by the PS2 and PS3 pipelines (logging, diagnostics, Vulkan
# inventory). Nothing console-specific belongs here.

set(RECOMP_VERSION "0.0.1" CACHE STRING "Version string reported in report.json")

# The commit can be passed in (Gradle does, so the APK and its native code agree); otherwise ask
# git. Configure-time value: reconfigure after committing to refresh it.
if(NOT DEFINED RECOMP_GIT_COMMIT OR RECOMP_GIT_COMMIT STREQUAL "")
    execute_process(COMMAND git rev-parse HEAD
        WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        OUTPUT_VARIABLE RECOMP_GIT_COMMIT OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET RESULT_VARIABLE _git_rc)
    if(NOT _git_rc EQUAL 0 OR RECOMP_GIT_COMMIT STREQUAL "")
        set(RECOMP_GIT_COMMIT "unknown")
    endif()
endif()
if(NOT DEFINED RECOMP_GIT_DIRTY)
    execute_process(COMMAND git status --porcelain --untracked-files=no
        WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        OUTPUT_VARIABLE _git_status ERROR_QUIET RESULT_VARIABLE _git_rc)
    if(_git_rc EQUAL 0 AND NOT _git_status STREQUAL "")
        set(RECOMP_GIT_DIRTY 1)
    else()
        set(RECOMP_GIT_DIRTY 0)
    endif()
endif()

if(ANDROID)
    set(RECOMP_TARGET_ABI "${ANDROID_ABI}")
else()
    set(RECOMP_TARGET_ABI "${CMAKE_SYSTEM_NAME}-${CMAKE_SYSTEM_PROCESSOR}")
endif()
set(RECOMP_BUILD_TYPE "${CMAKE_BUILD_TYPE}")

configure_file(build_info.h.in ${CMAKE_CURRENT_BINARY_DIR}/generated/recomp/build_info.h @ONLY)

find_path(RECOMP_VULKAN_INCLUDE_DIR vulkan/vulkan.h)
if(NOT RECOMP_VULKAN_INCLUDE_DIR)
    message(FATAL_ERROR "Vulkan headers not found (host: install libvulkan-dev; Android: the NDK ships them)")
endif()

add_library(recomp_common STATIC
    src/json.cpp
    src/log.cpp
    src/report.cpp
    src/vulkan_probe.cpp
)
target_include_directories(recomp_common
    PUBLIC include ${CMAKE_CURRENT_BINARY_DIR}/generated
    PRIVATE ${RECOMP_VULKAN_INCLUDE_DIR})
target_compile_features(recomp_common PUBLIC cxx_std_20)
target_compile_options(recomp_common PRIVATE -Wall -Wextra -Werror)
target_link_libraries(recomp_common PUBLIC ${CMAKE_DL_LIBS})
if(ANDROID)
    target_link_libraries(recomp_common PUBLIC log)
endif()
