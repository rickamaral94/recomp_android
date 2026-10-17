#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for tools/ps3/parse_rpcs3_log.py on a synthetic log in RPCS3's format."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools", "ps3"))
import parse_rpcs3_log as p  # noqa: E402

D = "·"
LOG = f"""﻿ARMSX3 v0.0.43-1-abcdef Alpha
{D}! 0:00:01.000000 SYS: Emulator::BootGame: path='<x>/Other.iso', title_id='', direct=0
{D}! 0:00:01.100000 SYS: Serial: BLES99999
{D}W 0:00:01.200000 ppu_loader: PPU executable hash: PPU-{'1' * 40}
{D}! 0:00:10.000000 SYS: Emulator::BootGame: path='<x>/Test.iso', title_id='', direct=0
{D}! 0:00:10.100000 SYS: Title: TEST GAME
{D}! 0:00:10.100001 SYS: Serial: TEST00001
{D}! 0:00:10.100002 SYS: Version: APP_VER=01.00 VERSION=01.00
{D}! 0:00:10.200000 ppu_loader: *** sdk version: 0x250001
{D}! 0:00:10.200001 ppu_loader: ** Segment: p_type=0x1, p_vaddr=0x10000, p_filesz=0x100, p_memsz=0x100, flags=0x400005
{D}W 0:00:10.300000 ppu_loader: PPU executable hash: PPU-{'a' * 40}
{D}W 0:00:10.310000 ppu_loader: SPU executable hash: SPU-{'b' * 40}
\tSegment: p_type=0x1, p_vaddr=0x80, p_filesz=0x7760, p_memsz=0x3ce80, p_offset=0x80 (image addr: 0xf73480, size: 0x7cdc)
{D}W 0:00:10.320000 ppu_loader: SPU executable hash: SPU-{'b' * 40}
{D}! 0:00:10.400000 ppu_loader: SELF header information found: ctrl_flags1=0x0, authid=0x1010000001000003
{D}! 0:00:10.400001 ppu_loader: ** Imported module 'cellSpurs' (ver=0x1, attr=0x9, 0x0, 0x0) [0xe5d844]
{D}! 0:00:10.400002 ppu_loader: **** cellSpurs import: [cellSpursFinalize] (0xca4c4600) -> 0xe5a96c
{D}! 0:00:10.400003 ppu_loader: **** cellSpurs import: [0x12345678] (0x12345678) -> 0xe5a98c
{D}W 0:00:10.500000 ppu_loader: Loading library: liblv2.sprx
{D}! 0:00:11.000000 {{PPU[0x1000000] Thread (main_thread) [0x00010000]}} cellSysutil TODO: cellAudioOutGetDeviceInfo(audioOut=0)
{D}W 0:00:11.100000 {{SPU[0x0000500] Thread (Job Manager - Job Thread) [0x0277c]}} SPU: something
{D}E 0:00:11.200000 {{PPU[0x1000000] Thread (main_thread) [0x00010000]}} sys_fs: 'sys_fs_open' failed with 0x80010006 : CELL_ENOENT, “/dev_hdd0/x”
{D}! 0:00:12.000000 {{PPU Syscall Usage Thread}} PPU: PPU Syscall Usage Stats:
\t⁂ sys_mutex_lock [10]
{D}! 0:00:22.000000 {{PPU Syscall Usage Thread}} PPU: PPU Syscall Usage Stats:
\t⁂ sys_mutex_lock [25]
\t⁂ sys_timer_usleep [4]
"""


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.r = p.parse(LOG.splitlines(True), source="synthetic.log")

    def test_boots_and_identity(self):
        self.assertEqual(self.r["emulator"], "ARMSX3 v0.0.43-1-abcdef Alpha")
        self.assertEqual([b["serial"] for b in self.r["boots"]], ["BLES99999", "TEST00001"])
        b = self.r["boots"][1]
        self.assertEqual(b["title"], "TEST GAME")
        self.assertEqual(b["app_ver"], "01.00")
        self.assertEqual(b["ppu_hash"]["value"], "PPU-" + "a" * 40)
        self.assertEqual(b["sdk_version"], "0x250001")
        self.assertEqual(b["self"]["authid"], "0x1010000001000003")
        self.assertEqual(b["segments"][0]["vaddr"], "0x10000")

    def test_imports(self):
        imp = self.r["boots"][1]["imports"]["cellSpurs"]
        self.assertEqual(imp["ver"], "0x1")
        self.assertEqual(imp["functions"][0], {"name": "cellSpursFinalize", "nid": "0xca4c4600", "stub": "0xe5a96c"})
        self.assertIsNone(imp["functions"][1]["name"])  # unknown NID stays unnamed
        self.assertEqual(self.r["boots"][1]["import_summary"], {"cellSpurs": 2})

    def test_spu_images_deduped_with_segment(self):
        spu = self.r["boots"][1]["spu_images"]
        self.assertEqual(len(spu), 1)
        self.assertEqual(spu[0]["occurrences"], 2)
        self.assertEqual(spu[0]["image_addr"], "0xf73480")
        self.assertEqual(spu[0]["image_size"], "0x7cdc")

    def test_runtime_facts(self):
        b = self.r["boots"][1]
        self.assertEqual(b["lle_libraries"], ["liblv2.sprx"])
        self.assertEqual(b["todo_calls"], {"cellSysutil::cellAudioOutGetDeviceInfo": 1})
        self.assertEqual(b["errors"], {"sys_fs::sys_fs_open -> CELL_ENOENT": 1})
        self.assertEqual(b["threads"]["SPU"], {"Job Manager - Job Thread": 1})
        # Cumulative stats: the last block wins.
        self.assertEqual(b["syscall_usage"]["counts"], {"sys_mutex_lock": 25, "sys_timer_usleep": 4})


if __name__ == "__main__":
    unittest.main()
