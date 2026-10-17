// SPDX-License-Identifier: GPL-3.0-or-later
#include "recomp/json.h"

#include <cstdio>
#include <stdexcept>

namespace recomp::json {

namespace {

// Length of the UTF-8 sequence starting at s[i], or 0 if it is not well formed.
size_t utf8_sequence_length(std::string_view s, size_t i) {
    const auto b0 = static_cast<unsigned char>(s[i]);
    size_t len;
    uint32_t min;
    if (b0 < 0x80) return 1;
    if ((b0 & 0xE0) == 0xC0) { len = 2; min = 0x80; }
    else if ((b0 & 0xF0) == 0xE0) { len = 3; min = 0x800; }
    else if ((b0 & 0xF8) == 0xF0) { len = 4; min = 0x10000; }
    else return 0;
    if (i + len > s.size()) return 0;
    uint32_t cp = b0 & (0x7F >> len);
    for (size_t k = 1; k < len; ++k) {
        const auto b = static_cast<unsigned char>(s[i + k]);
        if ((b & 0xC0) != 0x80) return 0;
        cp = (cp << 6) | (b & 0x3F);
    }
    if (cp < min || cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF)) return 0;
    return len;
}

} // namespace

std::string escape(std::string_view s) {
    std::string out;
    out.reserve(s.size() + 2);
    out.push_back('"');
    for (size_t i = 0; i < s.size();) {
        const auto c = static_cast<unsigned char>(s[i]);
        switch (c) {
        case '"': out += "\\\""; ++i; continue;
        case '\\': out += "\\\\"; ++i; continue;
        case '\b': out += "\\b"; ++i; continue;
        case '\f': out += "\\f"; ++i; continue;
        case '\n': out += "\\n"; ++i; continue;
        case '\r': out += "\\r"; ++i; continue;
        case '\t': out += "\\t"; ++i; continue;
        default: break;
        }
        if (c < 0x20) {
            char buf[8];
            std::snprintf(buf, sizeof buf, "\\u%04x", c);
            out += buf;
            ++i;
            continue;
        }
        const size_t len = utf8_sequence_length(s, i);
        if (len == 0) {
            out += "\xEF\xBF\xBD"; // U+FFFD
            ++i;
            continue;
        }
        out.append(s.data() + i, len);
        i += len;
    }
    out.push_back('"');
    return out;
}

void Writer::before_value() {
    if (stack_.empty()) {
        if (!out_.empty()) throw std::logic_error("json: more than one top-level value");
        return;
    }
    Frame& f = stack_.back();
    if (f.is_object) {
        if (!f.expect_value) throw std::logic_error("json: value without key inside object");
        f.expect_value = false;
        return;
    }
    if (!f.first) out_.push_back(',');
    f.first = false;
}

void Writer::key(std::string_view k) {
    if (stack_.empty() || !stack_.back().is_object) throw std::logic_error("json: key outside object");
    Frame& f = stack_.back();
    if (f.expect_value) throw std::logic_error("json: two keys in a row");
    if (!f.first) out_.push_back(',');
    f.first = false;
    out_ += escape(k);
    out_.push_back(':');
    f.expect_value = true;
}

void Writer::begin_object() {
    before_value();
    out_.push_back('{');
    stack_.push_back({true, true, false});
}

void Writer::end_object() {
    if (stack_.empty() || !stack_.back().is_object || stack_.back().expect_value)
        throw std::logic_error("json: unbalanced end_object");
    stack_.pop_back();
    out_.push_back('}');
}

void Writer::begin_array() {
    before_value();
    out_.push_back('[');
    stack_.push_back({false, true, false});
}

void Writer::end_array() {
    if (stack_.empty() || stack_.back().is_object) throw std::logic_error("json: unbalanced end_array");
    stack_.pop_back();
    out_.push_back(']');
}

void Writer::value(std::string_view s) {
    before_value();
    out_ += escape(s);
}

void Writer::value(bool b) {
    before_value();
    out_ += b ? "true" : "false";
}

void Writer::value(int64_t n) {
    before_value();
    out_ += std::to_string(n);
}

void Writer::value(uint64_t n) {
    before_value();
    out_ += std::to_string(n);
}

void Writer::null() {
    before_value();
    out_ += "null";
}

void Writer::raw(std::string_view json) {
    before_value();
    out_.append(json);
}

} // namespace recomp::json
