# SPDX-License-Identifier: GPL-3.0-or-later
#
# Host build: the shared native code (common/) plus its tests and the recomp-report CLI.
# The Android build reaches common/ through app/src/main/cpp/CMakeLists.txt instead.
cmake_minimum_required(VERSION 3.22)
project(recomp_android VERSION 0.0.1 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE RelWithDebInfo CACHE STRING "" FORCE)
endif()

add_subdirectory(common)

option(RECOMP_BUILD_TESTS "Build host tests" ON)
if(RECOMP_BUILD_TESTS AND NOT ANDROID)
    enable_testing()
    add_subdirectory(tests/host)
endif()
