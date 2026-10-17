// SPDX-License-Identifier: GPL-3.0-or-later
// Minimal JSON writer for report.json. Writing only: the app never parses its own reports.
#pragma once

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace recomp::json {

// Escapes a string per RFC 8259 (quotes, backslash, control characters). Input is treated as
// UTF-8 and passed through byte for byte; invalid UTF-8 is replaced with U+FFFD so the output
// is always valid JSON.
std::string escape(std::string_view s);

class Writer {
public:
    void begin_object();
    void end_object();
    void begin_array();
    void end_array();

    // Inside an object, key() must precede every value.
    void key(std::string_view k);

    void value(std::string_view s);
    void value(const char* s) { value(std::string_view(s)); }
    void value(bool b);
    void value(int64_t n);
    void value(uint64_t n);
    void value(int n) { value(static_cast<int64_t>(n)); }
    void value(unsigned n) { value(static_cast<uint64_t>(n)); }
    void null();

    // Inserts an already-serialised JSON value verbatim (caller guarantees validity).
    void raw(std::string_view json);

    const std::string& str() const { return out_; }

private:
    void before_value();

    struct Frame {
        bool is_object;
        bool first;
        bool expect_value; // object only: key() was called
    };
    std::vector<Frame> stack_;
    std::string out_;
};

} // namespace recomp::json
