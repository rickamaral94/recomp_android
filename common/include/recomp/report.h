// SPDX-License-Identifier: GPL-3.0-or-later
// report.json: schema "recomp_android.diagnostic-report", version 1. See docs/DIAGNOSTICO.md.
//
// Rule: a field that was not measured is reported as not collected (null plus a reason),
// never as zero or as a guess.
#pragma once

#include "recomp/vulkan_probe.h"

#include <string>
#include <vector>

namespace recomp::report {

inline constexpr const char* kSchema = "recomp_android.diagnostic-report";
inline constexpr int kSchemaVersion = 1;

// How far a port got. Ordered: each level implies the previous ones.
enum class Level {
    none,
    compiled,
    installed,
    opened,
    profile_loaded,
    reached_menu,
    reached_gameplay,
    stability_passed,
};
const char* level_name(Level level);

struct BuildInfo {
    std::string commit;     // git hash at configure time, "unknown" if not a git checkout
    bool dirty = false;     // uncommitted changes at configure time
    std::string version;
    std::string build_type;
    std::string abi;
    std::string compiler;
    std::string ndk;        // empty on host builds
};
BuildInfo current_build();

// Filled by the platform layer (Kotlin on Android, uname on host). Unknown fields stay empty.
struct DeviceInfo {
    std::string manufacturer;
    std::string model;
    std::string device;
    std::string os;               // "android" or the host OS
    std::string os_release;       // Android release ("14") or kernel release
    int sdk_int = 0;              // Android only, 0 elsewhere
    std::string soc_manufacturer; // Build.SOC_MANUFACTURER (API 31+)
    std::string soc_model;        // Build.SOC_MODEL (API 31+)
    std::string hardware;         // Build.HARDWARE
    std::vector<std::string> supported_abis;
};

struct TestResult {
    std::string name;
    std::string status; // "passed", "failed", "skipped"
    std::string detail;
};

struct Input {
    BuildInfo build;
    DeviceInfo device;
    vk::ProbeResult vulkan;
    Level level = Level::none;
    std::string level_note;
    std::vector<TestResult> tests;
    std::vector<std::string> limitations;
};

// generated_at is an ISO-8601 UTC timestamp supplied by the caller (keeps the output testable).
std::string to_json(const Input& in, const std::string& generated_at);

} // namespace recomp::report
