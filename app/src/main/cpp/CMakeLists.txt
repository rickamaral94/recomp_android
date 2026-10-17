# SPDX-License-Identifier: GPL-3.0-or-later
# Android entry point for the native code: recomp_common + the JNI bridge.
cmake_minimum_required(VERSION 3.22)
project(recompandroid LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../../../../common ${CMAKE_CURRENT_BINARY_DIR}/common)

add_library(recompandroid SHARED jni_bridge.cpp)
target_link_libraries(recompandroid PRIVATE recomp_common)
target_compile_options(recompandroid PRIVATE -Wall -Wextra -Werror)
# 16 KB pages (Android 15+ devices) as well as 4 KB.
target_link_options(recompandroid PRIVATE "-Wl,-z,max-page-size=16384")
