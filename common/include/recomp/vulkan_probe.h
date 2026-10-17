// SPDX-License-Identifier: GPL-3.0-or-later
// Read-only Vulkan inventory for the diagnostic report: loader version, physical devices,
// driver identity and device extensions. Loads libvulkan at run time so the library still
// works (and says why) on a system without Vulkan.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace recomp::vk {

struct DeviceInfo {
    std::string name;
    uint32_t vendor_id = 0;
    uint32_t device_id = 0;
    std::string device_type; // "integrated", "discrete", "virtual", "cpu", "other"
    uint32_t api_version = 0;
    uint32_t driver_version_raw = 0;
    std::string driver_version;  // decoded with the vendor's encoding, see decode_driver_version()
    bool has_driver_properties = false; // VK_KHR_driver_properties or Vulkan 1.2
    uint32_t driver_id = 0;
    std::string driver_name;
    std::string driver_info;
    std::vector<std::string> extensions; // sorted
};

struct ProbeResult {
    bool loader_found = false;
    bool instance_created = false;
    uint32_t instance_api_version = 0;
    std::vector<DeviceInfo> devices;
    std::string error; // empty on success
};

ProbeResult probe();

// "major.minor.patch" of a VK_MAKE_API_VERSION value.
std::string format_api_version(uint32_t v);

// Vendors encode driverVersion differently. NVIDIA uses 10.8.8.6 bits; Qualcomm (Adreno),
// ARM (Mali) and Mesa use the standard VK_MAKE_VERSION layout.
std::string decode_driver_version(uint32_t vendor_id, uint32_t raw);

} // namespace recomp::vk
