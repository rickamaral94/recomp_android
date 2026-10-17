#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""PPU differential test: qemu-ppc64 (oracle) vs. ps3recomp-lifted C on host and arm64.

Steps (all artefacts in --build):
  1. gen_cases.py -> kernel.S + cases.json
  2. clang (powerpc64 BE) -> kernel.o; the .text bytes -> kernel.bin (no relocations)
  3. oracle: kernel.o + a tiny _start -> static ELF, run under `qemu-ppc64 -cpu power7` -> oracle.bin
     Why POWER7: the Cell PPU is ISA 2.02 plus ldbrx/stdbrx, which POWER5+ (ISA 2.02) lacks and
     traps on; POWER7 (ISA 2.06) has them and still predates ISA 3.0's OV32/CA32 XER bits, which
     the Cell does not have. Nothing in the kernel uses an instruction the Cell lacks.
  4. lift kernel.bin with third_party/ps3recomp/tools/ppu_lifter.py -> C++
  5. build the lifted code + harness.cpp for the host and run it -> host.bin
  6. with --ndk: build a static arm64 Android executable, run it under qemu-aarch64 -> arm64.bin
  7. compare every record field (masked where the ISA leaves it undefined) -> report.json

Failures listed in known_divergences.json (understood, not yet fixed) are reported as known.
Exit status 0 only when every failure on every target is explained by an entry AND each
entry's failing-case count equals the count it pins for that target.
"""
import argparse
import collections
import glob
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
BASE = 0x10000
OUT_ADDR, SCRATCH_ADDR = 0x30000000, 0x20000000


def run(cmd, **kw):
    t = time.time()
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0:
        raise SystemExit(f"command failed ({r.returncode}): {' '.join(map(str, cmd))}")
    return time.time() - t


def tool(name, env=None):
    p = shutil.which(env and os.environ.get(env) or name)
    if not p:
        raise SystemExit(f"required tool not found: {name}")
    return p


START_S = """\
    .abiversion 2
    .text
    .globl _start
_start:
    lis 3, {out_hi:#x}
    lis 9, {scr_hi:#x}
    bl ppu_diff_kernel
    lis 4, {out_hi:#x}
    lis 5, {n_hi:#x}@l
    ori 5, 5, {n_lo:#x}
    bl .Lwrite_all
    lis 4, {scr_hi:#x}
    li 5, {scratch}
    bl .Lwrite_all
    li 3, 0
    li 0, 1
    sc
# write(1, r4, r5) until done; exit(3) on error
.Lwrite_all:
    cmpdi 5, 0
    beqlr
    li 3, 1
    li 0, 4
    sc
    bso .Lfail
    cmpdi 3, 0
    ble .Lfail
    add 4, 4, 3
    subf 5, 3, 5
    b .Lwrite_all
.Lfail:
    li 3, 3
    li 0, 1
    sc
    .section .outbuf,"aw",@nobits
    .space {n}
    .section .scratch,"aw",@nobits
    .space {scratch_alloc}
"""


def compare(cases_meta, oracle, other):
    rec = cases_meta["record_size"]
    n = cases_meta["count"]
    fails = []
    by_group = collections.defaultdict(lambda: [0, 0])
    fpscr_info = collections.Counter()
    for i, c in enumerate(cases_meta["cases"]):
        a = oracle[i * rec:(i + 1) * rec]
        b = other[i * rec:(i + 1) * rec]
        r7a, r8a, cra, xera = struct.unpack(">QQII8x", a)
        r7b, r8b, crb, xerb = struct.unpack(">QQII8x", b)
        m7, m8, mcr, mx = (int(c["masks"][k], 16) for k in ("r7", "r8", "cr", "xer"))
        diffs = {}
        if (r7a ^ r7b) & m7:
            diffs["r7"] = [f"{r7a:#018x}", f"{r7b:#018x}"]
        if (r8a ^ r8b) & m8:
            diffs["r8"] = [f"{r8a:#018x}", f"{r8b:#018x}"]
        if (cra ^ crb) & mcr:
            diffs["cr"] = [f"{cra:#010x}", f"{crb:#010x}"]
        if (xera ^ xerb) & mx:
            diffs["xer"] = [f"{xera:#010x}", f"{xerb:#010x}"]
        if c["kind"] == "fp" and xera != xerb:
            fpscr_info[c["group"]] += 1  # recorded, not compared (see gen_cases.py)
        g = by_group[c["group"]]
        g[0] += 1
        if diffs:
            g[1] += 1
            fails.append({"case": i, "name": c["name"], "group": c["group"], "inputs": c["inputs"],
                          "diff (oracle, lifted)": diffs})
    scratch_ok = oracle[n * rec:] == other[n * rec:]
    return {"cases": n, "failed": len(fails), "scratch_memory_equal": scratch_ok,
            "groups": {k: {"cases": v[0], "failed": v[1]} for k, v in sorted(by_group.items())},
            "fpscr_differs_informational": dict(sorted(fpscr_info.items())),
            "all_failures": fails}


def entry_matches(e, case):
    import re
    m = e["match"]
    if "groups" in m and case["group"] not in m["groups"]:
        return False
    if "name_regex" in m and not re.search(m["name_regex"], case["name"]):
        return False
    return True


def classify(report_target, target, known, cases=None):
    """Split failures into known entries / unexplained; check pinned counts. Returns problems.
    An entry whose cases are not in this run (a suite left out) is not checked."""
    hits = collections.Counter()
    unexplained = []
    for f in report_target["all_failures"]:
        for e in known["entries"]:
            if entry_matches(e, f):
                hits[e["id"]] += 1
                break
        else:
            unexplained.append(f)
    present = None if cases is None else {e["id"] for e in known["entries"]
                                          if any(entry_matches(e, c) for c in cases)}
    problems = []
    summary = {}
    for e in known["entries"]:
        want = e["expect"].get(target)
        if present is not None and e["id"] not in present:
            want = None
        got = hits.get(e["id"], 0)
        summary[e["id"]] = {"class": e["class"], "failing": got, "expected": want}
        if want is not None and got != want:
            problems.append(f"{e['id']}: {got} failing case(s), known_divergences.json expects {want}")
    if unexplained:
        problems.append(f"{len(unexplained)} failing case(s) not explained by known_divergences.json")
    return summary, unexplained, problems


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--build", required=True)
    ap.add_argument("--ps3recomp", default=os.path.join(ROOT, "third_party", "ps3recomp"))
    ap.add_argument("--ndk", help="Android NDK root: also build and run an arm64 static executable")
    ap.add_argument("--qemu-cpu", default="power7")
    ap.add_argument("--opt", default="-O1")
    ap.add_argument("--suites", default="int,fp,vmx,flow")
    a = ap.parse_args()
    b = os.path.abspath(a.build)
    os.makedirs(b, exist_ok=True)
    clang, clangxx = tool("clang", "CC"), tool("clang++", "CXX")
    lld, objcopy, qppc = tool("ld.lld"), tool("llvm-objcopy"), tool("qemu-ppc64")
    timings = {}

    timings["generate"] = run([sys.executable, "-I", os.path.join(HERE, "gen_cases.py"), b, "--suites", a.suites],
                              stdout=subprocess.DEVNULL)
    with open(os.path.join(b, "cases.json")) as f:
        meta = json.load(f)
    n_bytes = meta["count"] * meta["record_size"]

    ppc = ["--target=powerpc64-unknown-linux-gnu", "-mcpu=pwr7", "-c"]
    timings["assemble"] = run([clang, *ppc, os.path.join(b, "kernel.S"), "-o", os.path.join(b, "kernel.o")])
    relocs = subprocess.run([tool("llvm-readelf"), "-r", os.path.join(b, "kernel.o")],
                            capture_output=True, text=True, check=True).stdout
    if "Relocation section" in relocs:
        raise SystemExit("kernel.o has relocations: its raw .text bytes would not match the oracle's")
    run([objcopy, "-O", "binary", "--only-section=.text", os.path.join(b, "kernel.o"), os.path.join(b, "kernel.bin")])
    size = os.path.getsize(os.path.join(b, "kernel.bin"))

    with open(os.path.join(b, "start.S"), "w") as f:
        f.write(START_S.format(out_hi=OUT_ADDR >> 16, scr_hi=SCRATCH_ADDR >> 16, n=n_bytes,
                               n_hi=n_bytes >> 16, n_lo=n_bytes & 0xFFFF, scratch=meta["scratch_size"],
                               scratch_alloc=meta["scratch_alloc"]))
    run([clang, *ppc, os.path.join(b, "start.S"), "-o", os.path.join(b, "start.o")])
    # The kernel goes first in .text, at BASE: the same address it has in the lifted code and in
    # the RPCS3 executable, so absolute addresses (TOC slots, jump tables) agree in every world.
    run([lld, "-static", "--image-base=0x0", f"--section-start=.text={BASE:#x}",
         f"--section-start=.outbuf={OUT_ADDR:#x}", f"--section-start=.scratch={SCRATCH_ADDR:#x}",
         os.path.join(b, "kernel.o"), os.path.join(b, "start.o"), "-o", os.path.join(b, "oracle.elf")])
    nm_elf = subprocess.run([tool("llvm-nm"), os.path.join(b, "oracle.elf")], capture_output=True, text=True,
                            check=True).stdout
    if not any(l.split()[-1] == "ppu_diff_kernel" and int(l.split()[0], 16) == BASE for l in nm_elf.splitlines()):
        raise SystemExit("oracle.elf: ppu_diff_kernel is not at BASE")
    with open(os.path.join(b, "oracle.bin"), "wb") as out:
        timings["oracle_run"] = run([qppc, "-cpu", a.qemu_cpu, os.path.join(b, "oracle.elf")], stdout=out)

    # The lifter runs from a copy of ps3recomp's tools with patches/ps3recomp/*.patch applied;
    # the submodule itself stays pristine.
    tools_copy = os.path.join(b, "ps3recomp-tools")
    shutil.rmtree(tools_copy, ignore_errors=True)
    shutil.copytree(os.path.join(a.ps3recomp, "tools"), os.path.join(tools_copy, "tools"))
    patches = sorted(glob.glob(os.path.join(ROOT, "patches", "ps3recomp", "*.patch")))
    for pf in patches:
        run(["git", "apply", "-p1", pf], cwd=tools_copy)
    lifted = os.path.join(b, "lifted")
    shutil.rmtree(lifted, ignore_errors=True)
    # Function bounds from the kernel's own symbols (ppu_diff_kernel, ppu_diff_chunk_N).
    nm = subprocess.run([tool("llvm-nm"), "--defined-only", "-n", os.path.join(b, "kernel.o")],
                        capture_output=True, text=True, check=True).stdout.splitlines()
    # ppu_diff_* are functions; ppu_diffd_* are data (TOC, tables): a function ends at the next
    # symbol of either kind, so the data never falls inside a function.
    syms = sorted((int(l.split()[0], 16), l.split()[-1]) for l in nm
                  if l.strip() and l.split()[-1].startswith(("ppu_diff_", "ppu_diffd_")))
    ends = [x[0] for x in syms[1:]] + [size]
    bounds = [{"start": f"{BASE + a:#x}", "end": f"{BASE + e:#x}"}
              for (a, name), e in zip(syms, ends) if name.startswith("ppu_diff_")]
    toc = [a for a, name in syms if name == "ppu_diffd_toc"]
    with open(os.path.join(b, "functions.json"), "w") as f:
        json.dump(bounds, f)
    timings["lift"] = run([sys.executable, os.path.join(tools_copy, "tools", "ppu_lifter.py"),
                           os.path.join(b, "kernel.bin"), "--raw", "--base", f"{BASE:#x}",
                           "--functions", os.path.join(b, "functions.json"), "-o", lifted,
                           "--chunk-lines", "40000"] + (["--toc", f"{BASE + toc[0]:#x}"] if toc else []),
                          stdout=subprocess.DEVNULL)
    sources = sorted(os.path.join(lifted, s) for s in os.listdir(lifted) if s.endswith((".c", ".cpp")))
    incs = ["-I", lifted, "-I", os.path.join(a.ps3recomp, "runtime", "ppu"), "-I", os.path.join(a.ps3recomp, "include")]
    flags = ["-std=c++17", a.opt, "-w", "-fno-strict-aliasing"]

    def build(compiler, extra, tag):
        """Compile every source to an object in parallel, then link."""
        objdir = os.path.join(b, "obj-" + tag)
        os.makedirs(objdir, exist_ok=True)
        srcs = [os.path.join(HERE, "harness.cpp"), *sources]
        objs = [os.path.join(objdir, os.path.basename(s) + ".o") for s in srcs]
        with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as pool:
            list(pool.map(lambda so: run([compiler, *extra, *flags, *incs, "-c", so[0], "-o", so[1]]), zip(srcs, objs)))
        exe = os.path.join(b, "harness_" + tag)
        run([compiler, *extra, *objs, "-o", exe])
        return exe

    targets = {}
    t0 = time.time()
    host_exe = build(clangxx, [], "host")
    timings["build_host"] = time.time() - t0
    with open(os.path.join(b, "host.bin"), "wb") as out:
        timings["host_run"] = run([host_exe, str(n_bytes), os.path.join(b, "kernel.bin")], stdout=out)
    targets["host-" + os.uname().machine] = "host.bin"

    if a.ndk:
        ndk_clang = os.path.join(a.ndk, "toolchains", "llvm", "prebuilt", "linux-x86_64", "bin", "clang++")
        qa64 = tool("qemu-aarch64")
        t0 = time.time()
        arm_exe = build(ndk_clang, ["--target=aarch64-linux-android31", "-static"], "arm64")
        timings["build_arm64"] = time.time() - t0
        with open(os.path.join(b, "arm64.bin"), "wb") as out:
            timings["arm64_run_qemu"] = run([qa64, arm_exe, str(n_bytes), os.path.join(b, "kernel.bin")], stdout=out)
        targets["android-arm64 (qemu-aarch64)"] = "arm64.bin"

    with open(os.path.join(b, "oracle.bin"), "rb") as f:
        oracle = f.read()
    expected = n_bytes + meta["scratch_size"]
    if len(oracle) != expected:
        raise SystemExit(f"oracle wrote {len(oracle)} bytes, expected {expected}")
    report = {"schema": "recomp_android.ppu-diff-report", "schema_version": 1,
              "oracle": f"qemu-ppc64 -cpu {a.qemu_cpu} ({subprocess.run([qppc, '--version'], capture_output=True, text=True).stdout.splitlines()[0]})",
              "ps3recomp": subprocess.run(["git", "-C", a.ps3recomp, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip() or "unknown",
              "suites": a.suites, "kernel_bytes": size, "opt": a.opt,
              "ps3recomp_patches": [os.path.basename(pf) for pf in patches], "timings_s": {k: round(v, 2) for k, v in timings.items()},
              "targets": {}}
    with open(os.path.join(HERE, "known_divergences.json")) as f:
        known = json.load(f)
    ok = True
    for name, fn in targets.items():
        with open(os.path.join(b, fn), "rb") as f:
            data = f.read()
        if len(data) != expected:
            report["targets"][name] = {"error": f"wrote {len(data)} bytes, expected {expected}"}
            ok = False
            continue
        r = compare(meta, oracle, data)
        summary, unexplained, problems = classify(r, name, known, meta["cases"])
        r.pop("all_failures")
        r["known_divergences"] = summary
        r["unexplained_failures"] = unexplained[:200]
        r["problems"] = problems
        report["targets"][name] = r
        ok &= not problems and r["scratch_memory_equal"]
    with open(os.path.join(b, "report.json"), "w") as f:
        json.dump(report, f, indent=1)
    for name, r in report["targets"].items():
        if "error" in r:
            print(f"{name}: ERROR {r['error']}")
            continue
        known_n = sum(v["failing"] for v in r["known_divergences"].values())
        if r["fpscr_differs_informational"]:
            print(f"{name}: FPSCR differs (informational, not compared) in "
                  f"{sum(r['fpscr_differs_informational'].values())} FP cases")
        print(f"{name}: {r['cases'] - r['failed']}/{r['cases']} cases match, scratch "
              f"{'equal' if r['scratch_memory_equal'] else 'DIFFERENT'}; {known_n} known divergence(s), "
              f"{len(r['unexplained_failures'])} unexplained")
        for p in r["problems"]:
            print(f"{name}: PROBLEM: {p}")
    print("report:", os.path.join(b, "report.json"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
