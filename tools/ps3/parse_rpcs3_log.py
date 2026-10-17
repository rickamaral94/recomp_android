#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Extract port-relevant facts from an RPCS3/Armadasx3 log (ARMSX3.log, RPCS3.log).

Usage:
  parse_rpcs3_log.py LOG [LOG ...] [--serial BLUS30285] [-o OUT.json]

For every boot found (split at "Emulator::BootGame"), it reports:
  - title, serial, APP_VER and the emulator build line;
  - PPU executable hash, sdk version, SELF authid, program segments;
  - the import table: module -> functions with NID and stub address;
  - firmware libraries loaded by the emulator (LLE), e.g. liblv2.sprx;
  - SPU images embedded in the executable (hash, image address, size);
  - thread names seen per kind (PPU/SPU) with line counts;
  - syscall usage (last cumulative "PPU Syscall Usage Stats" block of the boot);
  - TODO / unimplemented HLE calls, and error lines grouped by function.

Everything here is what the emulator printed about the game, i.e. derived data: no code or
asset bytes. The source log line of each fact is kept ("line") so it can be checked.
"""
import argparse
import collections
import json
import re
import sys

PREFIX = re.compile(r"^·(?P<lvl>[A-Z!]) (?P<time>[0-9:.]+) (?:\{(?P<thread>[^}]*)\} )?(?P<msg>.*)$")

RE_BOOT = re.compile(r"SYS: Emulator::BootGame: path='(?P<path>[^']*)'")
RE_TITLE = re.compile(r"^SYS: Title: (?P<v>.*)$")
RE_SERIAL = re.compile(r"^SYS: Serial: (?P<v>\S+)")
RE_VERSION = re.compile(r"^SYS: Version: APP_VER=(?P<app>\S+) VERSION=(?P<ver>\S+)")
RE_PPU_HASH = re.compile(r"ppu_loader: PPU executable hash: (?P<v>PPU-[0-9a-f]{40})")
RE_SDK = re.compile(r"ppu_loader: \*\*\* sdk version: (?P<v>0x[0-9a-f]+)")
RE_SEGMENT = re.compile(r"ppu_loader: \*\* Segment: p_type=(?P<type>0x[0-9a-f]+), p_vaddr=(?P<vaddr>0x[0-9a-f]+), "
                        r"p_filesz=(?P<filesz>0x[0-9a-f]+), p_memsz=(?P<memsz>0x[0-9a-f]+), flags=(?P<flags>0x[0-9a-f]+)")
RE_AUTHID = re.compile(r"SELF header information found: ctrl_flags1=(?P<ctrl>0x[0-9a-f]+), authid=(?P<authid>0x[0-9a-f]+)")
RE_MODULE = re.compile(r"ppu_loader: \*\* Imported module '(?P<name>[^']+)' \(ver=(?P<ver>0x[0-9a-f]+), attr=(?P<attr>0x[0-9a-f]+)")
RE_IMPORT = re.compile(r"ppu_loader: \*\*\*\* (?P<module>\S+) import: \[(?P<name>[^\]]*)\] \((?P<nid>0x[0-9a-f]+)\) -> (?P<stub>0x[0-9a-f]+)")
RE_VAR_IMPORT = re.compile(r"ppu_loader: \*\*\*\* (?P<module>\S+) import variable: \[(?P<name>[^\]]*)\] \((?P<nid>0x[0-9a-f]+)\)")
RE_LIBRARY = re.compile(r"ppu_loader: Loading library: (?P<v>\S+)")
RE_SPU_HASH = re.compile(r"ppu_loader: SPU executable hash: (?P<v>SPU-[0-9a-f]{40})")
RE_SPU_SEG = re.compile(r"Segment: p_type=0x1, p_vaddr=(?P<vaddr>0x[0-9a-f]+), p_filesz=(?P<filesz>0x[0-9a-f]+), "
                        r"p_memsz=(?P<memsz>0x[0-9a-f]+), p_offset=0x[0-9a-f]+ \(image addr: (?P<addr>0x[0-9a-f]+), size: (?P<size>0x[0-9a-f]+)\)")
RE_STATS_HEAD = re.compile(r"PPU: PPU Syscall Usage Stats:")
RE_STATS_ROW = re.compile(r"^\s*⁂ (?P<name>\S+) \[(?P<count>\d+)\]")
RE_TODO = re.compile(r"^(?P<module>\S+) TODO: (?P<func>[A-Za-z_][A-Za-z0-9_]*)\(")
RE_UNIMPL = re.compile(r"^(?P<module>\S+): (?:Unimplemented|unimplemented)[^A-Za-z_]*(?P<func>[A-Za-z_][A-Za-z0-9_]*)")
RE_ERROR_FUNC = re.compile(r"^(?P<module>\S+): '(?P<func>[A-Za-z_][A-Za-z0-9_]*)' failed with (?P<code>0x[0-9a-f]+)(?: : (?P<name>[A-Z_0-9]+))?")
RE_NID_NAME = re.compile(r"^0x[0-9A-Fa-f]{8}$")
RE_THREAD = re.compile(r"^(?P<kind>PPU|SPU|RSX)\[0x[0-9a-f]+\] (?:Thread \((?P<name>[^)]*)\)|(?P<bare>.+))")


def new_boot(line_no, path):
    return {
        "line": line_no,
        "path": path,
        "title": None, "serial": None, "app_ver": None, "version": None,
        "ppu_hash": None, "sdk_version": None, "self": None,
        "segments": [],
        "imports": collections.OrderedDict(),
        "lle_libraries": [],
        "spu_images": [],
        "threads": {"PPU": collections.Counter(), "SPU": collections.Counter(), "RSX": collections.Counter()},
        "syscall_usage": None,
        "todo_calls": collections.Counter(),
        "errors": collections.Counter(),
        "level_counts": collections.Counter(),
    }


def parse(lines, source):
    emulator = None
    boots = []
    cur = None
    module_meta = {}
    stats_rows = None
    pending_spu = None
    for i, raw in enumerate(lines, 1):
        line = raw.rstrip("\n").lstrip("﻿")
        if emulator is None and re.match(r"^(ARMSX3|RPCS3) v\S+", line):
            emulator = line.strip()
        # A stats block is a header followed by indented rows without the log prefix.
        if stats_rows is not None:
            m = RE_STATS_ROW.match(line)
            if m:
                stats_rows[m["name"]] = int(m["count"])
                continue
            if cur is not None:
                cur["syscall_usage"] = {"line": stats_line, "counts": dict(stats_rows)}
            stats_rows = None
        if pending_spu is not None:
            m = RE_SPU_SEG.search(line)
            if m:
                pending_spu.update(image_addr=m["addr"], image_size=m["size"], ls_vaddr=m["vaddr"],
                                   filesz=m["filesz"], memsz=m["memsz"])
            pending_spu = None

        m = PREFIX.match(line)
        if not m:
            continue
        msg, thread, lvl = m["msg"], m["thread"], m["lvl"]

        b = RE_BOOT.search(msg)
        if b:
            cur = new_boot(i, b["path"])
            boots.append(cur)
            module_meta = {}
            continue
        if cur is None:
            continue
        cur["level_counts"][lvl] += 1

        if thread:
            t = RE_THREAD.match(thread)
            if t:
                name = t["name"] if t["name"] is not None else t["bare"]
                cur["threads"][t["kind"]][name.strip() or "(unnamed)"] += 1

        for rx, key in ((RE_TITLE, "title"), (RE_SERIAL, "serial")):
            mm = rx.match(msg)
            if mm and cur[key] is None:
                cur[key] = mm["v"].strip()
        mm = RE_VERSION.match(msg)
        if mm and cur["app_ver"] is None:
            cur["app_ver"], cur["version"] = mm["app"], mm["ver"]

        mm = RE_PPU_HASH.search(msg)
        if mm and cur["ppu_hash"] is None:
            cur["ppu_hash"] = {"value": mm["v"], "line": i}
            continue
        mm = RE_SDK.search(msg)
        if mm and cur["sdk_version"] is None:
            cur["sdk_version"] = mm["v"]
            continue
        mm = RE_SEGMENT.search(msg)
        if mm and cur["ppu_hash"] is None:  # program segments precede the PPU hash line
            cur["segments"].append({k: mm[k] for k in ("type", "vaddr", "filesz", "memsz", "flags")})
            continue
        mm = RE_AUTHID.search(msg)
        if mm and cur["self"] is None:
            cur["self"] = {"ctrl_flags1": mm["ctrl"], "authid": mm["authid"], "line": i}
            continue
        mm = RE_MODULE.search(msg)
        if mm:
            module_meta[mm["name"]] = {"ver": mm["ver"], "attr": mm["attr"]}
            cur["imports"].setdefault(mm["name"], {"ver": mm["ver"], "attr": mm["attr"], "line": i,
                                                   "functions": [], "variables": []})
            continue
        mm = RE_IMPORT.search(msg)
        if mm:
            mod = cur["imports"].setdefault(mm["module"], {"line": i, "functions": [], "variables": []})
            # RPCS3 prints an unknown NID in place of the name (e.g. "0x889864B4").
            name = mm["name"] if mm["name"] and not RE_NID_NAME.match(mm["name"]) else None
            mod["functions"].append({"name": name, "nid": mm["nid"], "stub": mm["stub"]})
            continue
        mm = RE_VAR_IMPORT.search(msg)
        if mm:
            mod = cur["imports"].setdefault(mm["module"], {"line": i, "functions": [], "variables": []})
            mod["variables"].append({"name": mm["name"] or None, "nid": mm["nid"]})
            continue
        mm = RE_LIBRARY.search(msg)
        if mm:
            if mm["v"] not in cur["lle_libraries"]:
                cur["lle_libraries"].append(mm["v"])
            continue
        mm = RE_SPU_HASH.search(msg)
        if mm:
            pending_spu = {"hash": mm["v"], "line": i}
            cur["spu_images"].append(pending_spu)
            continue
        if RE_STATS_HEAD.search(msg):
            stats_rows, stats_line = {}, i
            continue
        mm = RE_TODO.match(msg) or RE_UNIMPL.match(msg)
        if mm and mm["module"] != "SPU":
            cur["todo_calls"][f"{mm['module']}::{mm['func']}"] += 1
            continue
        if lvl in ("E", "F"):
            mm = RE_ERROR_FUNC.match(msg)
            key = f"{mm['module']}::{mm['func']} -> {mm['name'] or mm['code']}" if mm else re.sub(r"0x[0-9a-f]+", "0x…", msg)[:120]
            cur["errors"][key] += 1

    if stats_rows is not None and cur is not None:
        cur["syscall_usage"] = {"line": stats_line, "counts": dict(stats_rows)}

    for b in boots:
        b["source"] = source
        b["threads"] = {k: dict(v.most_common()) for k, v in b["threads"].items()}
        b["todo_calls"] = dict(b["todo_calls"].most_common())
        b["errors"] = dict(b["errors"].most_common())
        b["level_counts"] = dict(b["level_counts"])
        b["import_summary"] = {name: len(m["functions"]) for name, m in b["imports"].items()}
        # Dedupe repeated SPU images (same hash embedded several times), keep first sighting.
        seen = collections.OrderedDict()
        for s in b["spu_images"]:
            entry = seen.setdefault(s["hash"], dict(s, occurrences=0))
            entry["occurrences"] += 1
        b["spu_images"] = list(seen.values())
    return {"emulator": emulator, "boots": boots}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--serial", help="keep only boots of this serial")
    ap.add_argument("-o", "--output")
    a = ap.parse_args(argv)
    out = {"schema": "recomp_android.rpcs3-log-facts", "schema_version": 1, "logs": []}
    for path in a.logs:
        with open(path, encoding="utf-8", errors="replace") as f:
            r = parse(f, source=path.replace("\\", "/").rsplit("/", 1)[-1])
        if a.serial:
            r["boots"] = [b for b in r["boots"] if b["serial"] == a.serial]
        out["logs"].append(r)
    text = json.dumps(out, indent=1, ensure_ascii=False) + "\n"
    if a.output:
        with open(a.output, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
