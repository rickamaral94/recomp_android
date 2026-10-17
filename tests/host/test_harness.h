// SPDX-License-Identifier: GPL-3.0-or-later
// Tiny dependency-free test harness, so host tests build offline with only a compiler.
#pragma once

#include <cstdio>
#include <functional>
#include <string>
#include <vector>

namespace test {

struct Case {
    const char* name;
    std::function<void()> fn;
};

std::vector<Case>& registry();
extern int failures;

struct Register {
    Register(const char* name, std::function<void()> fn) { registry().push_back({name, std::move(fn)}); }
};

} // namespace test

#define TEST_CASE(name)                                          \
    static void name();                                          \
    static ::test::Register name##_registration(#name, name);    \
    static void name()

#define CHECK(cond)                                                                    \
    do {                                                                               \
        if (!(cond)) {                                                                 \
            std::fprintf(stderr, "  %s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #cond); \
            ++::test::failures;                                                        \
        }                                                                              \
    } while (0)

#define CHECK_EQ(a, b)                                                                       \
    do {                                                                                     \
        const auto& va_ = (a);                                                               \
        const auto& vb_ = (b);                                                               \
        if (!(va_ == vb_)) {                                                                 \
            std::fprintf(stderr, "  %s:%d: CHECK_EQ failed: %s == %s\n", __FILE__, __LINE__, #a, #b); \
            ++::test::failures;                                                              \
        }                                                                                    \
    } while (0)

#define CHECK_THROWS(expr)                                                                  \
    do {                                                                                    \
        bool threw_ = false;                                                                \
        try { expr; } catch (...) { threw_ = true; }                                        \
        if (!threw_) {                                                                      \
            std::fprintf(stderr, "  %s:%d: expected exception: %s\n", __FILE__, __LINE__, #expr); \
            ++::test::failures;                                                             \
        }                                                                                   \
    } while (0)
