// SPDX-License-Identifier: GPL-3.0-or-later
#include "recomp/report.h"

#include "recomp/build_info.h"
#include "recomp/json.h"

#ifdef __ANDROID__
#include <android/ndk-version.h>
#endif

namespace recomp::report {

namespace {

void not_collected(json::Writer& w, const char* key, const char* reason) {
    w.key(key);
    w.begin_object();
    w.key("collected");
    w.value(false);
    w.key("reason");
    w.value(reason);
    w.end_object();
}

void string_or_null(json::Writer& w, const char* key, const std::string& s) {
    w.key(key);
    if (s.empty())
        w.null();
    else
        w.value(s);
}

std::string hex32(uint32_t v) {
    static const char digits[] = "0123456789abcdef";
    std::string s = "0x00000000";
    for (int i = 0; i < 8; ++i) s[9 - i] = digits[(v >> (4 * i)) & 0xF];
    return s;
}

} // namespace

const char* level_name(Level level) {
    switch (level) {
    case Level::none: return "none";
    case Level::compiled: return "compiled";
    case Level::installed: return "installed";
    case Level::opened: return "opened";
    case Level::profile_loaded: return "profile_loaded";
    case Level::reached_menu: return "reached_menu";
    case Level::reached_gameplay: return "reached_gameplay";
    case Level::stability_passed: return "stability_passed";
    }
    return "none";
}

BuildInfo current_build() {
    BuildInfo b;
    b.commit = RECOMP_GIT_COMMIT;
    b.dirty = RECOMP_GIT_DIRTY != 0;
    b.version = RECOMP_VERSION;
    b.build_type = RECOMP_BUILD_TYPE;
    b.abi = RECOMP_TARGET_ABI;
#if defined(__clang__)
    b.compiler = "clang " __clang_version__;
#elif defined(__GNUC__)
    b.compiler = "gcc " __VERSION__;
#else
    b.compiler = "unknown";
#endif
#ifdef __ANDROID__
    b.ndk = std::to_string(__NDK_MAJOR__) + "." + std::to_string(__NDK_MINOR__) + "." +
            std::to_string(__NDK_BUILD__);
#endif
    return b;
}

std::string to_json(const Input& in, const std::string& generated_at) {
    json::Writer w;
    w.begin_object();
    w.key("schema");
    w.value(kSchema);
    w.key("schema_version");
    w.value(kSchemaVersion);
    w.key("generated_at");
    w.value(generated_at);

    w.key("build");
    w.begin_object();
    w.key("commit");
    w.value(in.build.commit);
    w.key("dirty");
    w.value(in.build.dirty);
    w.key("version");
    w.value(in.build.version);
    w.key("build_type");
    w.value(in.build.build_type);
    w.key("abi");
    w.value(in.build.abi);
    w.key("compiler");
    w.value(in.build.compiler);
    string_or_null(w, "ndk", in.build.ndk);
    w.end_object();

    const DeviceInfo& d = in.device;
    w.key("device");
    w.begin_object();
    string_or_null(w, "manufacturer", d.manufacturer);
    string_or_null(w, "model", d.model);
    string_or_null(w, "device", d.device);
    string_or_null(w, "os", d.os);
    string_or_null(w, "os_release", d.os_release);
    w.key("sdk_int");
    if (d.sdk_int > 0)
        w.value(d.sdk_int);
    else
        w.null();
    string_or_null(w, "soc_manufacturer", d.soc_manufacturer);
    string_or_null(w, "soc_model", d.soc_model);
    string_or_null(w, "hardware", d.hardware);
    w.key("supported_abis");
    w.begin_array();
    for (const auto& a : d.supported_abis) w.value(a);
    w.end_array();
    w.end_object();

    const vk::ProbeResult& v = in.vulkan;
    w.key("vulkan");
    w.begin_object();
    w.key("loader_found");
    w.value(v.loader_found);
    w.key("instance_created");
    w.value(v.instance_created);
    w.key("instance_api_version");
    if (v.loader_found)
        w.value(vk::format_api_version(v.instance_api_version));
    else
        w.null();
    string_or_null(w, "error", v.error);
    w.key("devices");
    w.begin_array();
    for (const auto& dev : v.devices) {
        w.begin_object();
        w.key("name");
        w.value(dev.name);
        w.key("vendor_id");
        w.value(hex32(dev.vendor_id));
        w.key("device_id");
        w.value(hex32(dev.device_id));
        w.key("type");
        w.value(dev.device_type);
        w.key("api_version");
        w.value(vk::format_api_version(dev.api_version));
        w.key("driver_version_raw");
        w.value(hex32(dev.driver_version_raw));
        w.key("driver_version");
        w.value(dev.driver_version);
        w.key("driver_id");
        if (dev.has_driver_properties)
            w.value(dev.driver_id);
        else
            w.null();
        string_or_null(w, "driver_name", dev.driver_name);
        string_or_null(w, "driver_info", dev.driver_info);
        w.key("extensions");
        w.begin_array();
        for (const auto& e : dev.extensions) w.value(e);
        w.end_array();
        w.end_object();
    }
    w.end_array();
    w.end_object();

    // Sections owned by later milestones. Present so the schema stays stable; never invented.
    w.key("game");
    w.null();
    w.key("analysis");
    w.begin_object();
    w.key("tools");
    w.begin_array();
    w.end_array();
    w.key("findings");
    w.begin_array();
    w.end_array();
    w.end_object();
    w.key("recompilation");
    w.null();
    w.key("metrics");
    w.begin_object();
    not_collected(w, "frame_time", "no console pipeline in this build");
    not_collected(w, "cpu_gpu_time", "no console pipeline in this build");
    not_collected(w, "audio", "no console pipeline in this build");
    not_collected(w, "thermal", "not implemented");
    not_collected(w, "cpu_frequencies", "not implemented");
    w.end_object();

    w.key("tests");
    w.begin_array();
    for (const auto& t : in.tests) {
        w.begin_object();
        w.key("name");
        w.value(t.name);
        w.key("status");
        w.value(t.status);
        string_or_null(w, "detail", t.detail);
        w.end_object();
    }
    w.end_array();

    w.key("result");
    w.begin_object();
    w.key("level");
    w.value(level_name(in.level));
    string_or_null(w, "note", in.level_note);
    w.end_object();

    w.key("limitations");
    w.begin_array();
    for (const auto& l : in.limitations) w.value(l);
    w.end_array();

    w.end_object();
    return w.str();
}

} // namespace recomp::report
