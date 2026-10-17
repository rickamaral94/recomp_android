#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for tools/ps3/hle_coverage.py on a synthetic runtime tree."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools", "ps3"))
import hle_coverage as h  # noqa: E402

SRC = """\
s32 cellFoo(u32 a)
{
    return 0;
}
int64_t sys_one_liner(ppu_context* ctx) { return go(ctx); }
s32 cellOnlyDeclared(u32 a);
static void reg(void) { lv2_syscall_register(tbl, 1, sys_registered_by_table); }
"""


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        with open(os.path.join(self.tmp.name, "a.c"), "w") as f:
            f.write(SRC)
        with open(os.path.join(self.tmp.name, "a.h"), "w") as f:
            f.write("s32 cellInHeaderOnly(void);\n")
        self.names, self.mentions = h.scan(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_classify(self):
        c = lambda n: h.classify(n, self.names, self.mentions)[0]  # noqa: E731
        self.assertEqual(c("cellFoo"), "defined")
        self.assertEqual(c("sys_one_liner"), "defined")
        self.assertEqual(c("cellOnlyDeclared"), "mentioned")
        self.assertEqual(c("sys_registered_by_table"), "mentioned")
        self.assertEqual(c("cellInHeaderOnly"), "mentioned")
        self.assertEqual(c("cellNowhere"), "absent")
        self.assertEqual(c(None), "absent")

    def test_coverage_counts(self):
        facts = {"logs": [{"boots": [{
            "serial": "TEST00001", "ppu_hash": {"value": "PPU-x"},
            "import_summary": {"m": 3},
            "imports": {"m": {"functions": [
                {"name": "cellFoo", "nid": "0x1"},
                {"name": "cellOnlyDeclared", "nid": "0x2"},
                {"name": None, "nid": "0x3"}]}},
            "syscall_usage": {"counts": {"sys_one_liner": 5, "sys_missing": 1}},
        }]}]}
        r = h.coverage(facts, self.names, self.mentions)
        self.assertEqual(r["imports"], {"defined": 1, "mentioned": 1, "absent": 1})
        self.assertEqual(r["modules"]["m"]["absent_names"], ["0x3"])
        self.assertEqual(r["syscalls"], {"defined": 1, "mentioned": 0, "absent": 1})
        self.assertEqual(r["syscall_rows"][0]["name"], "sys_one_liner")  # sorted by calls


if __name__ == "__main__":
    unittest.main()
