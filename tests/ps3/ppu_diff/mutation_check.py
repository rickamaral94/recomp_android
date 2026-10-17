#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check that the PPU differential test can fail: break the lifted code on purpose and
require run_diff.compare to report every mutant.

Usage: mutation_check.py BUILD_DIR   (a directory run_diff.py already filled)

Mutants, each applied at the first site per source file and at every site:
  - carry flag computed with <= instead of <
  - XER[SO] no longer copied into CR0 by record forms
  - the harness stores little-endian instead of big-endian
Exit status 0 only when every mutant is detected.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
import run_diff  # noqa: E402

MUTANTS = [
    ("carry < becomes <=", "lifted", r"\(result < ctx->gpr\[(\d+)\]\)", r"(result <= ctx->gpr[\1])"),
    ("CR0 loses XER[SO]", "lifted", r"_c \|= \(uint32_t\)\(\(ctx->xer >> 31\) & 1u\);", "_c |= 0u;"),
    ("little-endian guest stores", "harness", re.escape("p[sizeof(T) - 1 - i] = static_cast<uint8_t>(v >> (8 * i));"),
     "p[i] = static_cast<uint8_t>(v >> (8 * i));"),
]


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    b = os.path.abspath(sys.argv[1])
    with open(os.path.join(b, "cases.json")) as f:
        meta = json.load(f)
    with open(os.path.join(b, "oracle.bin"), "rb") as f:
        oracle = f.read()
    n = meta["count"] * meta["record_size"]
    sources = sorted(glob.glob(os.path.join(b, "lifted", "*.cpp")))
    cxx = shutil.which(os.environ.get("CXX", "clang++"))
    all_detected = True
    for name, where, pat, rep in MUTANTS:
        for count, mode in ((1, "first site per file"), (0, "every site")):
            d = os.path.join(b, "mutant")
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d)
            shutil.copy(os.path.join(b, "lifted", "ppu_recomp.h"), d)
            applied = 0
            files = []
            for src in sources:
                text = open(src).read()
                if where == "lifted":
                    text, k = re.subn(pat, rep, text, count=count)
                    applied += k
                dst = os.path.join(d, os.path.basename(src))
                open(dst, "w").write(text)
                files.append(dst)
            harness = open(os.path.join(HERE, "harness.cpp")).read()
            if where == "harness":
                harness, applied = re.subn(pat, rep, harness, count=count)
            open(os.path.join(d, "harness.cpp"), "w").write(harness)
            if applied == 0:
                print(f"{name} [{mode}]: pattern not found -- the lifter output changed; update the mutant")
                all_detected = False
                continue
            exe = os.path.join(d, "harness")
            subprocess.run([cxx, "-std=c++17", "-O1", "-w", "-fno-strict-aliasing", "-I", d,
                            "-I", os.path.join(ROOT, "third_party", "ps3recomp", "runtime", "ppu"),
                            os.path.join(d, "harness.cpp"), *files, "-o", exe], check=True)
            out = subprocess.run([exe, str(n)], capture_output=True).stdout
            if len(out) != n + meta["scratch_size"]:
                print(f"{name} [{mode}]: applied at {applied} site(s); mutant did not finish -> detected")
                continue
            r = run_diff.compare(meta, oracle, out)
            detected = r["failed"] > 0 or not r["scratch_memory_equal"]
            all_detected &= detected
            print(f"{name} [{mode}]: applied at {applied} site(s); {r['failed']} case(s) differ -> "
                  f"{'detected' if detected else 'MISSED'}")
    shutil.rmtree(os.path.join(b, "mutant"), ignore_errors=True)
    return 0 if all_detected else 1


if __name__ == "__main__":
    sys.exit(main())
