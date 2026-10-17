// SPDX-License-Identifier: GPL-3.0-or-later
#include "recomp/json.h"
#include "test_harness.h"

using recomp::json::escape;
using recomp::json::Writer;

TEST_CASE(json_escape_basic) {
    CHECK_EQ(escape("abc"), std::string("\"abc\""));
    CHECK_EQ(escape("a\"b\\c"), std::string("\"a\\\"b\\\\c\""));
    CHECK_EQ(escape("\n\t\r\b\f"), std::string("\"\\n\\t\\r\\b\\f\""));
    CHECK_EQ(escape(std::string_view("\x01\x1f", 2)), std::string("\"\\u0001\\u001f\""));
    CHECK_EQ(escape(std::string_view("\0", 1)), std::string("\"\\u0000\""));
}

TEST_CASE(json_escape_utf8) {
    CHECK_EQ(escape("ação"), std::string("\"ação\""));          // valid 2-byte sequences kept
    CHECK_EQ(escape("\xF0\x9F\x8E\xAE"), std::string("\"\xF0\x9F\x8E\xAE\"")); // 4-byte kept
    CHECK_EQ(escape("a\xFFz"), std::string("\"a\xEF\xBF\xBDz\""));  // invalid byte -> U+FFFD
    CHECK_EQ(escape("\xC3"), std::string("\"\xEF\xBF\xBD\""));       // truncated sequence
    CHECK_EQ(escape("\xC0\x80"), std::string("\"\xEF\xBF\xBD\xEF\xBF\xBD\"")); // overlong
    CHECK_EQ(escape("\xED\xA0\x80"), std::string("\"\xEF\xBF\xBD\xEF\xBF\xBD\xEF\xBF\xBD\"")); // surrogate
}

TEST_CASE(json_writer_nesting) {
    Writer w;
    w.begin_object();
    w.key("a");
    w.value(1);
    w.key("b");
    w.begin_array();
    w.value(true);
    w.null();
    w.value("x");
    w.begin_object();
    w.end_object();
    w.end_array();
    w.key("c");
    w.value(static_cast<uint64_t>(18446744073709551615ull));
    w.key("d");
    w.value(static_cast<int64_t>(-5));
    w.end_object();
    CHECK_EQ(w.str(), std::string(R"({"a":1,"b":[true,null,"x",{}],"c":18446744073709551615,"d":-5})"));
}

TEST_CASE(json_writer_rejects_misuse) {
    {
        Writer w;
        w.begin_object();
        CHECK_THROWS(w.value(1)); // value without key
    }
    {
        Writer w;
        w.begin_array();
        CHECK_THROWS(w.key("k")); // key inside array
    }
    {
        Writer w;
        w.begin_object();
        w.key("k");
        CHECK_THROWS(w.end_object()); // dangling key
    }
    {
        Writer w;
        w.value(1);
        CHECK_THROWS(w.value(2)); // second top-level value
    }
    {
        Writer w;
        w.begin_array();
        CHECK_THROWS(w.end_object());
    }
}
