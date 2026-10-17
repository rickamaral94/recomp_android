// SPDX-License-Identifier: GPL-3.0-or-later
// Session logger shared by every pipeline. Writes to stderr (host) or logcat (Android) and,
// once open_file() succeeds, to a plain-text file that goes into the diagnostic ZIP.
#pragma once

#include <string>
#include <string_view>

namespace recomp::log {

enum class Level { debug, info, warn, error };

// Opens (truncates) the session log file. Returns false and keeps logging to stderr/logcat
// only if the file cannot be opened.
bool open_file(const std::string& path);
void close_file();

void write(Level level, std::string_view tag, std::string_view message);

inline void debug(std::string_view tag, std::string_view m) { write(Level::debug, tag, m); }
inline void info(std::string_view tag, std::string_view m) { write(Level::info, tag, m); }
inline void warn(std::string_view tag, std::string_view m) { write(Level::warn, tag, m); }
inline void error(std::string_view tag, std::string_view m) { write(Level::error, tag, m); }

const char* level_name(Level level);

} // namespace recomp::log
