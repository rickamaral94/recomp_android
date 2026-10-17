// SPDX-License-Identifier: GPL-3.0-or-later
#include "test_harness.h"

#include <cstring>

namespace test {
std::vector<Case>& registry() {
    static std::vector<Case> r;
    return r;
}
int failures = 0;
} // namespace test

int main(int argc, char** argv) {
    const char* filter = argc > 1 ? argv[1] : nullptr;
    int run = 0, failed_cases = 0;
    for (const auto& c : test::registry()) {
        if (filter && !std::strstr(c.name, filter)) continue;
        const int before = test::failures;
        try {
            c.fn();
        } catch (const std::exception& e) {
            std::fprintf(stderr, "  unexpected exception: %s\n", e.what());
            ++test::failures;
        }
        ++run;
        const bool ok = test::failures == before;
        if (!ok) ++failed_cases;
        std::printf("[%s] %s\n", ok ? "PASS" : "FAIL", c.name);
    }
    std::printf("%d cases, %d failed\n", run, failed_cases);
    return failed_cases == 0 && run > 0 ? 0 : 1;
}
