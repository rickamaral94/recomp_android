// SPDX-License-Identifier: GPL-3.0-or-later
// JNI surface of librecompandroid.so. Kept thin: everything testable lives in common/.
#include "recomp/log.h"
#include "recomp/report.h"

#include <jni.h>

#include <string>
#include <vector>

namespace {

std::string to_string(JNIEnv* env, jstring s) {
    if (!s) return {};
    const char* chars = env->GetStringUTFChars(s, nullptr);
    std::string out = chars ? chars : "";
    if (chars) env->ReleaseStringUTFChars(s, chars);
    return out;
}

std::vector<std::string> to_strings(JNIEnv* env, jobjectArray arr) {
    std::vector<std::string> out;
    if (!arr) return out;
    const jsize n = env->GetArrayLength(arr);
    for (jsize i = 0; i < n; ++i) {
        auto s = static_cast<jstring>(env->GetObjectArrayElement(arr, i));
        out.push_back(to_string(env, s));
        env->DeleteLocalRef(s);
    }
    return out;
}

} // namespace

extern "C" {

JNIEXPORT jboolean JNICALL
Java_io_github_rickamaral94_recompandroid_NativeBridge_openLog(JNIEnv* env, jobject, jstring path) {
    const bool ok = recomp::log::open_file(to_string(env, path));
    recomp::log::info("app", ok ? "session log opened" : "session log could not be opened");
    return ok ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT void JNICALL
Java_io_github_rickamaral94_recompandroid_NativeBridge_log(JNIEnv* env, jobject, jint level, jstring tag,
                                                           jstring message) {
    const auto lv = static_cast<recomp::log::Level>(level < 0 ? 0 : level > 3 ? 3 : level);
    recomp::log::write(lv, to_string(env, tag), to_string(env, message));
}

JNIEXPORT jbyteArray JNICALL
Java_io_github_rickamaral94_recompandroid_NativeBridge_buildReport(
    JNIEnv* env, jobject, jobjectArray device_fields, jint sdk_int, jobjectArray abis, jstring generated_at) {
    using namespace recomp;
    // device_fields order is fixed by NativeBridge.kt: manufacturer, model, device, release,
    // socManufacturer, socModel, hardware.
    const auto f = to_strings(env, device_fields);
    auto at = [&](size_t i) { return i < f.size() ? f[i] : std::string(); };

    report::Input in;
    in.build = report::current_build();
    in.device.manufacturer = at(0);
    in.device.model = at(1);
    in.device.device = at(2);
    in.device.os = "android";
    in.device.os_release = at(3);
    in.device.sdk_int = sdk_int;
    in.device.soc_manufacturer = at(4);
    in.device.soc_model = at(5);
    in.device.hardware = at(6);
    in.device.supported_abis = to_strings(env, abis);

    in.vulkan = vk::probe();
    if (in.vulkan.instance_created) {
        log::info("vulkan", "probe ok: " + std::to_string(in.vulkan.devices.size()) + " device(s)");
        for (const auto& d : in.vulkan.devices)
            log::info("vulkan", d.name + " driver " + d.driver_version + " (" + d.driver_name + " " +
                                    d.driver_info + "), api " + vk::format_api_version(d.api_version));
    } else {
        log::error("vulkan", "probe failed: " + in.vulkan.error);
    }
    in.tests.push_back({"vulkan_probe", in.vulkan.instance_created ? "passed" : "failed", in.vulkan.error});

    // The app is running, so it compiled, installed and opened. Nothing beyond that exists yet.
    in.level = report::Level::opened;
    in.level_note = "M0 app shell; no PS2 or PS3 pipeline in this build";
    in.limitations.push_back("M0 skeleton: no PS2 or PS3 pipeline is built yet");
    in.limitations.push_back("frame time, thermal and CPU frequency are not collected yet");

    // Returned as UTF-8 bytes: NewStringUTF takes modified UTF-8 and would mangle 4-byte sequences.
    const std::string json = report::to_json(in, to_string(env, generated_at));
    jbyteArray out = env->NewByteArray(static_cast<jsize>(json.size()));
    if (out) env->SetByteArrayRegion(out, 0, static_cast<jsize>(json.size()), reinterpret_cast<const jbyte*>(json.data()));
    return out;
}

} // extern "C"
