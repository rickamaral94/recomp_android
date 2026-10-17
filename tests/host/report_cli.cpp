// SPDX-License-Identifier: GPL-3.0-or-later
// recomp-report: prints the host's report.json to stdout (same code path the app uses).
#include "recomp/report.h"

#include <sys/utsname.h>

#include <cstdio>
#include <ctime>

int main() {
    using namespace recomp;
    report::Input in;
    in.build = report::current_build();

    utsname u{};
    if (uname(&u) == 0) {
        in.device.os = u.sysname;
        in.device.os_release = u.release;
        in.device.hardware = u.machine;
    }

    in.vulkan = vk::probe();
    in.tests.push_back({"vulkan_probe", in.vulkan.instance_created ? "passed" : "failed", in.vulkan.error});
    in.level = report::Level::compiled;
    in.level_note = "host CLI; no console pipeline";
    in.limitations.push_back("M0 skeleton: no PS2 or PS3 pipeline is built yet");

    char ts[32];
    const std::time_t t = std::time(nullptr);
    std::tm tm{};
    gmtime_r(&t, &tm);
    std::strftime(ts, sizeof ts, "%Y-%m-%dT%H:%M:%SZ", &tm);

    std::puts(report::to_json(in, ts).c_str());
    return 0;
}
