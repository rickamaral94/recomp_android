#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for tools/ps3/inventory.py on synthetic dumps (no game data)."""
import hashlib
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools", "ps3"))
import inventory  # noqa: E402


def make_sfo(entries):
    """entries: list of (key, value) with str (utf8, fmt 0x0204) or int (fmt 0x0404)."""
    keys = b""
    data = b""
    index = b""
    for key, value in entries:
        if isinstance(value, int):
            raw, fmt = struct.pack("<I", value), 0x0404
            max_len = 4
        else:
            raw, fmt = value.encode() + b"\0", 0x0204
            max_len = (len(raw) + 3) & ~3
        index += struct.pack("<HHIII", len(keys), fmt, len(raw), max_len, len(data))
        keys += key.encode() + b"\0"
        data += raw.ljust(max_len, b"\0")
    keys = keys.ljust((len(keys) + 3) & ~3, b"\0")
    key_start = 20 + len(index)
    data_start = key_start + len(keys)
    return b"\0PSF" + struct.pack("<IIII", 0x101, key_start, data_start, len(entries)) + index + keys + data


SFO = make_sfo([("APP_VER", "01.00"), ("ATTRIBUTE", 32), ("CATEGORY", "DG"),
                ("PS3_SYSTEM_VER", "02.7000"), ("TITLE", "SYNTHETIC TEST"),
                ("TITLE_ID", "TEST00001"), ("VERSION", "01.00")])
EBOOT = b"SCE\0" + bytes(range(256)) * 9


def dir_record(name, lba, size, is_dir):
    n = name.encode()
    length = 33 + len(n) + (1 if len(n) % 2 == 0 else 0)
    rec = bytearray(length)
    rec[0] = length
    struct.pack_into("<I", rec, 2, lba)
    struct.pack_into(">I", rec, 6, lba)
    struct.pack_into("<I", rec, 10, size)
    struct.pack_into(">I", rec, 14, size)
    rec[25] = 2 if is_dir else 0
    rec[32] = len(n)
    rec[33:33 + len(n)] = n
    return bytes(rec)


def make_iso(path):
    """Minimal ISO 9660: / -> PS3_GAME/ -> PARAM.SFO, USRDIR/ -> EBOOT.BIN."""
    S = inventory.SECTOR
    root, game, usrdir, sfo_lba, eboot_lba = 20, 21, 22, 23, 24
    sectors = {}

    def dir_sector(self_lba, parent_lba, children):
        body = dir_record("\0", self_lba, S, True) + dir_record("\1", parent_lba, S, True)
        for c in children:
            body += c
        return body.ljust(S, b"\0")

    sectors[root] = dir_sector(root, root, [dir_record("PS3_GAME", game, S, True)])
    sectors[game] = dir_sector(game, root, [dir_record("PARAM.SFO;1", sfo_lba, len(SFO), False),
                                            dir_record("USRDIR", usrdir, S, True)])
    sectors[usrdir] = dir_sector(usrdir, game, [dir_record("EBOOT.BIN;1", eboot_lba, len(EBOOT), False)])
    pvd = bytearray(S)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    pvd[156:156 + 34] = dir_record("\0", root, S, True)[:34]
    sectors[16] = bytes(pvd)
    sectors[sfo_lba] = SFO.ljust(S, b"\0")
    eboot_sectors = (len(EBOOT) + S - 1) // S
    with open(path, "wb") as f:
        for lba in range(eboot_lba):
            f.write(sectors.get(lba, b"\0" * S))
        f.write(EBOOT.ljust(eboot_sectors * S, b"\0"))


class InventoryTests(unittest.TestCase):
    def check(self, result, kind):
        self.assertEqual(result["schema"], "recomp_android.ps3-inventory")
        self.assertEqual(result["source_kind"], kind)
        self.assertEqual(result["param_sfo"]["TITLE_ID"], "TEST00001")
        self.assertEqual(result["param_sfo"]["APP_VER"], "01.00")
        self.assertEqual(result["param_sfo"]["CATEGORY"], "DG")
        files = {f["path"]: f for f in result["files"]}
        self.assertEqual(files["PS3_GAME/PARAM.SFO"]["sha256"], hashlib.sha256(SFO).hexdigest())
        eboot = files["PS3_GAME/USRDIR/EBOOT.BIN"]
        self.assertEqual(eboot["sha256"], hashlib.sha256(EBOOT).hexdigest())
        self.assertEqual(eboot["size"], len(EBOOT))
        self.assertTrue(eboot["format"].startswith("SELF"))

    def test_sfo_int_and_strings(self):
        sfo = inventory.parse_sfo(SFO)
        self.assertEqual(sfo["ATTRIBUTE"], 32)
        self.assertEqual(sfo["TITLE"], "SYNTHETIC TEST")

    def test_sfo_rejects_garbage(self):
        with self.assertRaises(ValueError):
            inventory.parse_sfo(b"not an sfo at all....")
        with self.assertRaises(ValueError):
            inventory.parse_sfo(SFO[:24])

    def test_folder(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "PS3_GAME", "USRDIR"))
            with open(os.path.join(d, "PS3_GAME", "PARAM.SFO"), "wb") as f:
                f.write(SFO)
            with open(os.path.join(d, "PS3_GAME", "USRDIR", "EBOOT.BIN"), "wb") as f:
                f.write(EBOOT)
            self.check(inventory.inventory(d), "folder")
            # The PS3_GAME folder itself is accepted too.
            self.check(inventory.inventory(os.path.join(d, "PS3_GAME")), "folder")
            allf = inventory.inventory(d, all_files=True)
            self.assertEqual(len(allf["files"]), 2)
            # No absolute path in the output.
            self.assertNotIn(d, repr(allf))

    def test_iso(self):
        with tempfile.TemporaryDirectory() as d:
            iso = os.path.join(d, "test.iso")
            make_iso(iso)
            r = inventory.inventory(iso)
            self.check(r, "iso")
            with open(iso, "rb") as f:
                self.assertEqual(r["iso"]["sha256"], hashlib.sha256(f.read()).hexdigest())
            allf = inventory.inventory(iso, all_files=True)
            self.assertEqual(sorted(x["path"] for x in allf["files"]),
                             ["PS3_GAME/PARAM.SFO", "PS3_GAME/USRDIR/EBOOT.BIN"])

    def test_missing_eboot_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "PS3_GAME"))
            with open(os.path.join(d, "PS3_GAME", "PARAM.SFO"), "wb") as f:
                f.write(SFO)
            r = inventory.inventory(d)
            self.assertTrue(any(x.get("missing") for x in r["files"]))

    def test_not_a_dump(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                inventory.inventory(d)
            p = os.path.join(d, "x.iso")
            with open(p, "wb") as f:
                f.write(b"\0" * 40000)
            with self.assertRaises(ValueError):
                inventory.inventory(p)


if __name__ == "__main__":
    unittest.main()
