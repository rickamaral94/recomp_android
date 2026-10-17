// SPDX-License-Identifier: GPL-3.0-or-later
#include "recomp/vulkan_probe.h"

#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>

#include <dlfcn.h>

#include <algorithm>
#include <cstring>

namespace recomp::vk {

namespace {

constexpr uint32_t kVendorNvidia = 0x10DE;

const char* device_type_name(VkPhysicalDeviceType t) {
    switch (t) {
    case VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU: return "integrated";
    case VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU: return "discrete";
    case VK_PHYSICAL_DEVICE_TYPE_VIRTUAL_GPU: return "virtual";
    case VK_PHYSICAL_DEVICE_TYPE_CPU: return "cpu";
    default: return "other";
    }
}

struct Library {
    void* handle = nullptr;
    ~Library() {
        if (handle) dlclose(handle);
    }
};

} // namespace

std::string format_api_version(uint32_t v) {
    return std::to_string(VK_API_VERSION_MAJOR(v)) + "." + std::to_string(VK_API_VERSION_MINOR(v)) +
           "." + std::to_string(VK_API_VERSION_PATCH(v));
}

std::string decode_driver_version(uint32_t vendor_id, uint32_t raw) {
    if (vendor_id == kVendorNvidia) {
        return std::to_string((raw >> 22) & 0x3FF) + "." + std::to_string((raw >> 14) & 0xFF) + "." +
               std::to_string((raw >> 6) & 0xFF) + "." + std::to_string(raw & 0x3F);
    }
    return std::to_string(raw >> 22) + "." + std::to_string((raw >> 12) & 0x3FF) + "." +
           std::to_string(raw & 0xFFF);
}

ProbeResult probe() {
    ProbeResult r;
    Library lib;
    for (const char* name : {"libvulkan.so", "libvulkan.so.1"}) {
        lib.handle = dlopen(name, RTLD_NOW | RTLD_LOCAL);
        if (lib.handle) break;
    }
    if (!lib.handle) {
        r.error = "libvulkan not found";
        return r;
    }
    r.loader_found = true;

    auto gipa = reinterpret_cast<PFN_vkGetInstanceProcAddr>(dlsym(lib.handle, "vkGetInstanceProcAddr"));
    if (!gipa) {
        r.error = "vkGetInstanceProcAddr missing";
        return r;
    }

    r.instance_api_version = VK_API_VERSION_1_0;
    if (auto eiv = reinterpret_cast<PFN_vkEnumerateInstanceVersion>(gipa(nullptr, "vkEnumerateInstanceVersion")))
        eiv(&r.instance_api_version);

    auto create_instance = reinterpret_cast<PFN_vkCreateInstance>(gipa(nullptr, "vkCreateInstance"));
    if (!create_instance) {
        r.error = "vkCreateInstance missing";
        return r;
    }

    // Ask for 1.1 when the loader has it: vkGetPhysicalDeviceProperties2 is core there.
    const uint32_t requested = r.instance_api_version >= VK_API_VERSION_1_1 ? VK_API_VERSION_1_1 : VK_API_VERSION_1_0;
    VkApplicationInfo app{};
    app.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
    app.pApplicationName = "recomp_android-probe";
    app.apiVersion = requested;
    VkInstanceCreateInfo ci{};
    ci.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    ci.pApplicationInfo = &app;
    VkInstance instance = VK_NULL_HANDLE;
    const VkResult res = create_instance(&ci, nullptr, &instance);
    if (res != VK_SUCCESS) {
        r.error = "vkCreateInstance failed: VkResult " + std::to_string(static_cast<int>(res));
        return r;
    }
    r.instance_created = true;

#define LOAD(fn) auto fn = reinterpret_cast<PFN_##fn>(gipa(instance, #fn))
    LOAD(vkDestroyInstance);
    LOAD(vkEnumeratePhysicalDevices);
    LOAD(vkGetPhysicalDeviceProperties);
    LOAD(vkGetPhysicalDeviceProperties2);
    LOAD(vkEnumerateDeviceExtensionProperties);
#undef LOAD
    if (requested < VK_API_VERSION_1_1) vkGetPhysicalDeviceProperties2 = nullptr;

    if (!vkDestroyInstance || !vkEnumeratePhysicalDevices || !vkGetPhysicalDeviceProperties ||
        !vkEnumerateDeviceExtensionProperties) {
        r.error = "instance entry points missing";
        if (vkDestroyInstance) vkDestroyInstance(instance, nullptr);
        return r;
    }

    uint32_t count = 0;
    vkEnumeratePhysicalDevices(instance, &count, nullptr);
    std::vector<VkPhysicalDevice> pds(count);
    if (count) vkEnumeratePhysicalDevices(instance, &count, pds.data());
    pds.resize(count);

    for (VkPhysicalDevice pd : pds) {
        VkPhysicalDeviceProperties p{};
        vkGetPhysicalDeviceProperties(pd, &p);
        DeviceInfo d;
        d.name = p.deviceName;
        d.vendor_id = p.vendorID;
        d.device_id = p.deviceID;
        d.device_type = device_type_name(p.deviceType);
        d.api_version = p.apiVersion;
        d.driver_version_raw = p.driverVersion;
        d.driver_version = decode_driver_version(p.vendorID, p.driverVersion);

        uint32_t ext_count = 0;
        vkEnumerateDeviceExtensionProperties(pd, nullptr, &ext_count, nullptr);
        std::vector<VkExtensionProperties> exts(ext_count);
        if (ext_count) vkEnumerateDeviceExtensionProperties(pd, nullptr, &ext_count, exts.data());
        exts.resize(ext_count);
        for (const auto& e : exts) d.extensions.emplace_back(e.extensionName);
        std::sort(d.extensions.begin(), d.extensions.end());

        const bool has_ext = std::binary_search(d.extensions.begin(), d.extensions.end(),
                                                std::string(VK_KHR_DRIVER_PROPERTIES_EXTENSION_NAME));
        if (vkGetPhysicalDeviceProperties2 && (has_ext || p.apiVersion >= VK_API_VERSION_1_2)) {
            VkPhysicalDeviceDriverProperties drv{};
            drv.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES;
            VkPhysicalDeviceProperties2 p2{};
            p2.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2;
            p2.pNext = &drv;
            vkGetPhysicalDeviceProperties2(pd, &p2);
            d.has_driver_properties = true;
            d.driver_id = static_cast<uint32_t>(drv.driverID);
            d.driver_name = drv.driverName;
            d.driver_info = drv.driverInfo;
        }
        r.devices.push_back(std::move(d));
    }

    vkDestroyInstance(instance, nullptr);
    return r;
}

} // namespace recomp::vk
