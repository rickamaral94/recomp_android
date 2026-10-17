// SPDX-License-Identifier: GPL-3.0-or-later
#include "recomp/log.h"

#include <chrono>
#include <cstdio>
#include <ctime>
#include <mutex>

#ifdef __ANDROID__
#include <android/log.h>
#endif

namespace recomp::log {

namespace {

std::mutex g_mutex;
FILE* g_file = nullptr;

std::string timestamp_utc() {
    using namespace std::chrono;
    const auto now = system_clock::now();
    const auto ms = duration_cast<milliseconds>(now.time_since_epoch()).count() % 1000;
    const std::time_t t = system_clock::to_time_t(now);
    std::tm tm{};
    gmtime_r(&t, &tm);
    char buf[64];
    std::snprintf(buf, sizeof buf, "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ", tm.tm_year + 1900,
                  tm.tm_mon + 1, tm.tm_mday, tm.tm_hour, tm.tm_min, tm.tm_sec, static_cast<int>(ms));
    return buf;
}

} // namespace

const char* level_name(Level level) {
    switch (level) {
    case Level::debug: return "D";
    case Level::info: return "I";
    case Level::warn: return "W";
    case Level::error: return "E";
    }
    return "?";
}

bool open_file(const std::string& path) {
    std::lock_guard lock(g_mutex);
    if (g_file) std::fclose(g_file);
    g_file = std::fopen(path.c_str(), "w");
    return g_file != nullptr;
}

void close_file() {
    std::lock_guard lock(g_mutex);
    if (g_file) std::fclose(g_file);
    g_file = nullptr;
}

void write(Level level, std::string_view tag, std::string_view message) {
    const std::string line = timestamp_utc() + " " + level_name(level) + " [" + std::string(tag) +
                             "] " + std::string(message) + "\n";
    std::lock_guard lock(g_mutex);
#ifdef __ANDROID__
    static constexpr int prio[] = {ANDROID_LOG_DEBUG, ANDROID_LOG_INFO, ANDROID_LOG_WARN, ANDROID_LOG_ERROR};
    __android_log_print(prio[static_cast<int>(level)], "recomp", "[%.*s] %.*s",
                        static_cast<int>(tag.size()), tag.data(),
                        static_cast<int>(message.size()), message.data());
#else
    std::fputs(line.c_str(), stderr);
#endif
    if (g_file) {
        std::fputs(line.c_str(), g_file);
        std::fflush(g_file);
    }
}

} // namespace recomp::log
