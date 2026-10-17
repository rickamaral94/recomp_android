// SPDX-License-Identifier: GPL-3.0-or-later
#include "recomp/vulkan_probe.h"
#include "test_harness.h"

#include <cstdlib>

using namespace recomp::vk;

TEST_CASE(vk_driver_version_decoding) {
    // Qualcomm proprietary Adreno driver 512.744 (standard VK_MAKE_VERSION layout).
    CHECK_EQ(decode_driver_version(0x5143, 0x802E8000), std::string("512.744.0"));
    // Mesa (Turnip, lavapipe): 25.2.8.
    CHECK_EQ(decode_driver_version(0x10005, (25u << 22) | (2u << 12) | 8u), std::string("25.2.8"));
    // NVIDIA 10.8.8.6 layout: 535.104.5.0.
    CHECK_EQ(decode_driver_version(0x10DE, (535u << 22) | (104u << 14) | (5u << 6)), std::string("535.104.5.0"));
    CHECK_EQ(format_api_version((1u << 22) | (3u << 12) | 275u), std::string("1.3.275"));
}

// Runs the real probe. Without a Vulkan loader it must fail cleanly with a reason. With
// RECOMP_EXPECT_VULKAN=1 (set in CI, where lavapipe is installed) it must find a device.
TEST_CASE(vk_probe_real_system) {
    const ProbeResult r = probe();
    const char* expect = std::getenv("RECOMP_EXPECT_VULKAN");
    if (expect && std::string(expect) == "1") {
        CHECK(r.loader_found);
        CHECK(r.instance_created);
        CHECK(r.error.empty());
        CHECK(!r.devices.empty());
        for (const auto& d : r.devices) {
            CHECK(!d.name.empty());
            CHECK(!d.driver_version.empty());
            for (size_t i = 1; i < d.extensions.size(); ++i) CHECK(d.extensions[i - 1] <= d.extensions[i]);
        }
    } else if (!r.instance_created) {
        CHECK(!r.error.empty());
        CHECK(r.devices.empty());
    }
}
