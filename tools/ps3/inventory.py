#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Identify a PS3 game dump locally, without copying or decrypting anything.

Usage:
  inventory.py PATH [--all-files] [-o OUT.json]

PATH is one of:
  - a disc folder (contains PS3_GAME/) or the PS3_GAME folder itself;
  - an .iso image (ISO 9660). Only the file system is read; nothing is decrypted.

The output is a JSON summary for games/ps3/<ID>/: PARAM.SFO fields (TITLE_ID, TITLE, APP_VER,
VERSION, CATEGORY, PS3_SYSTEM_VER), SHA-256 and size of PARAM.SFO and EBOOT.BIN, and the
executable's container format read from its magic bytes (SCE = signed/encrypted SELF,
ELF = plain). Paths are relative to the dump; no absolute path leaves your machine.

Run it on your own machine. The output holds hashes and metadata, not game content.
"""
import argparse
import hashlib
import json
import os
import struct
import sys

SECTOR = 2048
CHUNK = 1 << 20


# --- PARAM.SFO -------------------------------------------------------------------------------

def parse_sfo(data):
    """Return {key: value} from a PARAM.SFO blob. Raises ValueError if it is not one."""
    if len(data) < 20 or data[:4] != b"\0PSF":
        raise ValueError("not a PARAM.SFO (bad magic)")
    _version, key_start, data_start, count = struct.unpack_from("<IIII", data, 4)
    if 20 + 16 * count > len(data):
        raise ValueError("PARAM.SFO index runs past end of file")
    out = {}
    for i in range(count):
        key_off, fmt, length, _max_len, data_off = struct.unpack_from("<HHIII", data, 20 + 16 * i)
        k0 = key_start + key_off
        k1 = data.find(b"\0", k0)
        if k0 >= len(data) or k1 < 0:
            raise ValueError("PARAM.SFO key out of range")
        key = data[k0:k1].decode("utf-8", "replace")
        v0 = data_start + data_off
        raw = data[v0:v0 + length]
        if len(raw) != length:
            raise ValueError(f"PARAM.SFO value for {key} out of range")
        if fmt == 0x0404:
            out[key] = struct.unpack("<I", raw[:4])[0] if length >= 4 else None
        else:  # 0x0004 (utf8-s) and 0x0204 (utf8, NUL-terminated)
            out[key] = raw.split(b"\0", 1)[0].decode("utf-8", "replace")
    return out


SFO_KEYS = ("TITLE_ID", "TITLE", "APP_VER", "VERSION", "CATEGORY", "PS3_SYSTEM_VER")


def executable_format(head):
    if head[:4] == b"SCE\0":
        return "SELF (signed; encrypted unless fake-signed)"
    if head[:4] == b"\x7fELF":
        return "ELF (plain)"
    return "unknown"


# --- Sources: folder or ISO 9660 -------------------------------------------------------------

class FolderSource:
    def __init__(self, path):
        root = path
        if os.path.isdir(os.path.join(path, "PS3_GAME")):
            root = os.path.join(path, "PS3_GAME")
        if not os.path.isfile(os.path.join(root, "PARAM.SFO")):
            raise ValueError("no PS3_GAME/PARAM.SFO under this folder")
        self.root = root
        self.kind = "folder"

    def close(self):
        pass

    def read(self, rel):
        with open(os.path.join(self.root, *rel.split("/")), "rb") as f:
            return f.read()

    def stream(self, rel):
        p = os.path.join(self.root, *rel.split("/"))
        if not os.path.isfile(p):
            return None
        return os.path.getsize(p), open(p, "rb")

    def walk(self):
        for dirpath, _dirs, files in os.walk(self.root):
            for name in files:
                full = os.path.join(dirpath, name)
                yield os.path.relpath(full, self.root).replace(os.sep, "/")


class _Slice:
    """File-like view of [start, start+size) of an open file."""

    def __init__(self, f, start, size):
        self.f, self.pos, self.end = f, start, start + size

    def read(self, n=-1):
        if n < 0 or self.pos + n > self.end:
            n = self.end - self.pos
        self.f.seek(self.pos)
        b = self.f.read(n)
        self.pos += len(b)
        return b

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class IsoSource:
    def __init__(self, path):
        self.f = open(path, "rb")
        self.kind = "iso"
        try:
            self._open()
        except BaseException:
            self.f.close()
            raise

    def close(self):
        self.f.close()

    def _open(self):
        pvd = self._sector(16)
        if pvd[1:6] != b"CD001" or pvd[0] != 1:
            raise ValueError("not an ISO 9660 image (no primary volume descriptor at sector 16)")
        root_lba, root_size = self._record_extent(pvd[156:156 + 34])
        self.root = (root_lba, root_size)
        game = self._lookup(self.root, "PS3_GAME")
        if not game or not game[2]:
            raise ValueError("no PS3_GAME directory in the ISO")
        self.game = game[:2]

    def _sector(self, lba, count=1):
        self.f.seek(lba * SECTOR)
        return self.f.read(SECTOR * count)

    @staticmethod
    def _record_extent(rec):
        return struct.unpack_from("<I", rec, 2)[0], struct.unpack_from("<I", rec, 10)[0]

    def _entries(self, extent):
        lba, size = extent
        data = self._sector(lba, (size + SECTOR - 1) // SECTOR)[:size]
        i = 0
        while i < len(data):
            n = data[i]
            if n == 0:  # records do not cross sectors; skip to the next one
                i = (i // SECTOR + 1) * SECTOR
                continue
            rec = data[i:i + n]
            name_len = rec[32]
            name = rec[33:33 + name_len]
            is_dir = bool(rec[25] & 2)
            if name not in (b"\0", b"\1"):
                text = name.decode("ascii", "replace").split(";", 1)[0]
                elba, esize = self._record_extent(rec)
                yield text, elba, esize, is_dir
            i += n

    def _lookup(self, extent, name):
        for text, lba, size, is_dir in self._entries(extent):
            if text.upper() == name.upper():
                return lba, size, is_dir
        return None

    def _resolve(self, rel):
        extent = self.game
        parts = rel.split("/")
        for k, part in enumerate(parts):
            hit = self._lookup(extent, part)
            if not hit:
                return None
            if k < len(parts) - 1 and not hit[2]:
                return None
            extent = hit[:2]
        return extent

    def read(self, rel):
        ext = self._resolve(rel)
        if not ext:
            raise FileNotFoundError(rel)
        self.f.seek(ext[0] * SECTOR)
        return self.f.read(ext[1])

    def stream(self, rel):
        ext = self._resolve(rel)
        if not ext:
            return None
        return ext[1], _Slice(self.f, ext[0] * SECTOR, ext[1])

    def walk(self):
        def rec(extent, prefix):
            for text, lba, size, is_dir in self._entries(extent):
                path = f"{prefix}{text}"
                if is_dir:
                    yield from rec((lba, size), path + "/")
                else:
                    yield path
        yield from rec(self.game, "")


def open_source(path):
    if os.path.isdir(path):
        return FolderSource(path)
    return IsoSource(path)


# --- Inventory -------------------------------------------------------------------------------

def sha256_stream(f):
    h = hashlib.sha256()
    head = b""
    while True:
        b = f.read(CHUNK)
        if not b:
            break
        if not head:
            head = b[:16]
        h.update(b)
    return h.hexdigest(), head


def file_entry(src, rel):
    s = src.stream(rel)
    if s is None:
        return None
    size, f = s
    with f:
        digest, head = sha256_stream(f)
    return {"path": f"PS3_GAME/{rel}", "size": size, "sha256": digest, "head": head}


def inventory(path, all_files=False):
    src = open_source(path)
    try:
        return _inventory(src, path, all_files)
    finally:
        src.close()


def _inventory(src, path, all_files):
    sfo_raw = src.read("PARAM.SFO")
    sfo = parse_sfo(sfo_raw)
    out = {
        "schema": "recomp_android.ps3-inventory",
        "schema_version": 1,
        "source_kind": src.kind,
        "param_sfo": {k: sfo.get(k) for k in SFO_KEYS},
        "files": [],
    }
    if src.kind == "iso":
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            out["iso"] = {"size": size, "sha256": sha256_stream(f)[0]}

    targets = ["PARAM.SFO", "USRDIR/EBOOT.BIN"]
    if all_files:
        targets = sorted(set(targets) | set(src.walk()))
    for rel in targets:
        e = file_entry(src, rel)
        if e is None:
            out["files"].append({"path": f"PS3_GAME/{rel}", "missing": True})
            continue
        head = e.pop("head")
        if rel == "USRDIR/EBOOT.BIN":
            e["format"] = executable_format(head)
        out["files"].append(e)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("path")
    ap.add_argument("--all-files", action="store_true", help="hash every file under PS3_GAME (slow)")
    ap.add_argument("-o", "--output")
    a = ap.parse_args(argv)
    try:
        result = inventory(a.path, a.all_files)
    except (ValueError, OSError) as e:
        print(f"inventory: {e}", file=sys.stderr)
        return 1
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if a.output:
        with open(a.output, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
