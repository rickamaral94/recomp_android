// SPDX-License-Identifier: GPL-3.0-or-later
#include "recomp/report.h"
#include "test_harness.h"

using namespace recomp;

namespace {
bool contains(const std::string& s, const std::string& needle) {
    return s.find(needle) != std::string::npos;
}
} // namespace

TEST_CASE(report_level_names_are_ordered_ladder) {
    CHECK_EQ(std::string(report::level_name(report::Level::compiled)), std::string("compiled"));
    CHECK_EQ(std::string(report::level_name(report::Level::stability_passed)), std::string("stability_passed"));
    CHECK(report::Level::opened < report::Level::reached_menu);
    CHECK(report::Level::reached_menu < report::Level::reached_gameplay);
}

TEST_CASE(report_build_info_is_filled) {
    const auto b = report::current_build();
    CHECK(!b.commit.empty());
    CHECK(!b.version.empty());
    CHECK(!b.abi.empty());
    CHECK(!b.compiler.empty());
}

TEST_CASE(report_unmeasured_fields_are_not_invented) {
    report::Input in;
    in.build = report::current_build();
    in.vulkan.error = "libvulkan not found";
    const std::string j = report::to_json(in, "2026-01-01T00:00:00Z");
    CHECK(contains(j, R"("schema":"recomp_android.diagnostic-report")"));
    CHECK(contains(j, R"("schema_version":1)"));
    CHECK(contains(j, R"("generated_at":"2026-01-01T00:00:00Z")"));
    CHECK(contains(j, R"("game":null)"));
    CHECK(contains(j, R"("recompilation":null)"));
    CHECK(contains(j, R"("frame_time":{"collected":false)"));
    CHECK(contains(j, R"("thermal":{"collected":false)"));
    CHECK(contains(j, R"("sdk_int":null)"));
    CHECK(contains(j, R"("instance_api_version":null)"));
    CHECK(contains(j, R"("error":"libvulkan not found")"));
    CHECK(contains(j, R"("result":{"level":"none")"));
}

TEST_CASE(report_device_and_vulkan_fields) {
    report::Input in;
    in.build = report::current_build();
    in.device.manufacturer = "AYN";
    in.device.model = "Odin2 Portal";
    in.device.os = "android";
    in.device.sdk_int = 33;
    in.device.soc_model = "SM8550";
    in.device.supported_abis = {"arm64-v8a"};
    in.vulkan.loader_found = true;
    in.vulkan.instance_created = true;
    in.vulkan.instance_api_version = (1u << 22) | (3u << 12);
    vk::DeviceInfo d;
    d.name = "Adreno (TM) 740";
    d.vendor_id = 0x5143;
    d.device_type = "integrated";
    d.api_version = (1u << 22) | (3u << 12) | 128;
    d.driver_version_raw = 0x802E8000;
    d.driver_version = vk::decode_driver_version(d.vendor_id, d.driver_version_raw);
    d.extensions = {"VK_KHR_swapchain"};
    in.vulkan.devices.push_back(d);
    in.level = report::Level::opened;
    in.tests.push_back({"vulkan_probe", "passed", ""});

    const std::string j = report::to_json(in, "t");
    CHECK(contains(j, R"("model":"Odin2 Portal")"));
    CHECK(contains(j, R"("sdk_int":33)"));
    CHECK(contains(j, R"("instance_api_version":"1.3.0")"));
    CHECK(contains(j, R"("vendor_id":"0x00005143")"));
    CHECK(contains(j, R"("api_version":"1.3.128")"));
    CHECK(contains(j, R"("driver_version":"512.744.0")"));
    CHECK(contains(j, R"("driver_id":null)"));
    CHECK(contains(j, R"("extensions":["VK_KHR_swapchain"])"));
    CHECK(contains(j, R"("level":"opened")"));
    CHECK(contains(j, R"({"name":"vulkan_probe","status":"passed","detail":null})"));
}
