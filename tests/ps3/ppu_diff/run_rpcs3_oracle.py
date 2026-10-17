#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Second oracle: run the differential-test kernel in RPCS3's PPU interpreter.

Usage: run_rpcs3_oracle.py --build BUILD_DIR --rpcs3 PATH/TO/rpcs3 --rpcs3-src RPCS3_CHECKOUT [--timeout S]

No firmware is used. RPCS3 refuses to boot without it while any firmware library is set to LLE,
so every library its g_prx_list marks LLE-by-default (read from RPCS3_CHECKOUT's
rpcs3/Emu/Cell/lv2/sys_prx.cpp) is forced to HLE. The kernel imports none of them.

BUILD_DIR is a directory run_diff.py already filled (kernel.bin, cases.json, oracle.bin and the
lifted outputs host.bin / arm64.bin). The kernel is wrapped in a PS3 executable (ps3_elf.py),
run headless in an isolated RPCS3 home with the static interpreter and every PPU accuracy option
on, and its results come back through TTY.log.

The report (BUILD_DIR/report_rpcs3.json) answers three questions per case:
  - do the two oracles (qemu-ppc64 POWER7 and RPCS3) agree?
  - does each lifted target match RPCS3?
  - for each entry of known_divergences.json, which side does RPCS3 take?
Where the oracles disagree, neither is assumed right: that needs hardware.

RPCS3 is used as a separate program, never linked into this project.
"""
import argparse
import collections
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ps3_elf  # noqa: E402
import run_diff  # noqa: E402

CONFIG_YML = """\
Core:
  PPU Decoder: Interpreter (static)
  PPU Set Saturation Bit: true
  PPU Accurate Non-Java Mode: true
  PPU Set FPCC Bits: true
  PPU Accurate Vector NaN Values: true
  PPU Vector NaN Handling: true
  Use Accurate DFMA: true
  PPU Accurate Vector Estimates: true
Video:
  Renderer: Null
Audio:
  Renderer: Null
Miscellaneous:
  Exit RPCS3 when process finishes: true
"""


def lle_default_libs(rpcs3_src):
    src = open(os.path.join(rpcs3_src, "rpcs3", "Emu", "Cell", "lv2", "sys_prx.cpp")).read()
    i = src.index("g_prx_list")
    pairs = re.findall(r'\{\s*"([^"]+)"\s*,\s*(\d)\s*\}', src[i:src.index("};", i)])
    if not pairs:
        raise SystemExit("could not read g_prx_list from sys_prx.cpp")
    return [name for name, lle in pairs if lle == "0"]


def failing_set(meta, a, b):
    return {f["case"]: f for f in run_diff.compare(meta, a, b)["all_failures"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--build", required=True)
    ap.add_argument("--rpcs3", required=True)
    ap.add_argument("--rpcs3-src", required=True, help="the RPCS3 checkout the binary was built from")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--home", default=os.path.expanduser("~/.cache/recomp_android-rpcs3-oracle"),
                    help="isolated RPCS3 home; RPCS3 refuses to run from a temporary directory such as /tmp")
    a = ap.parse_args()
    b = os.path.abspath(a.build)
    with open(os.path.join(b, "cases.json")) as f:
        meta = json.load(f)
    n = meta["count"] * meta["record_size"]
    img, total = ps3_elf.build(os.path.join(b, "kernel.bin"), n, meta["scratch_size"], meta["scratch_alloc"], b)
    elf = os.path.join(b, "ps3_kernel.elf")
    with open(elf, "wb") as f:
        f.write(img)

    home = os.path.abspath(a.home)
    shutil.rmtree(home, ignore_errors=True)
    os.makedirs(os.path.join(home, "config", "rpcs3"))
    os.makedirs(os.path.join(home, "cache", "rpcs3"))
    libs = lle_default_libs(a.rpcs3_src)
    config = CONFIG_YML.replace("Core:\n", "Core:\n  Libraries Control: [" + ", ".join(f'"{x}:hle"' for x in libs) + "]\n", 1)
    with open(os.path.join(home, "config", "rpcs3", "config.yml"), "w") as f:
        f.write(config)
    env = dict(os.environ, HOME=home, XDG_CONFIG_HOME=os.path.join(home, "config"),
               XDG_CACHE_HOME=os.path.join(home, "cache"), QT_QPA_PLATFORM="offscreen")
    tty = os.path.join(home, "cache", "rpcs3", "TTY.log")
    log = os.path.join(home, "cache", "rpcs3", "RPCS3.log")

    t0 = time.time()
    with open(os.path.join(b, "rpcs3_stdout.log"), "w") as out:
        proc = subprocess.Popen([a.rpcs3, "--headless", elf], env=env, stdout=out, stderr=subprocess.STDOUT)
        data = None
        while time.time() - t0 < a.timeout:
            if proc.poll() is not None:
                break
            time.sleep(2)
            if os.path.exists(tty):
                try:
                    data = ps3_elf.tty_to_bin(open(tty, errors="replace").read(), total)
                    break  # everything printed; RPCS3 may linger after the process exits
                except ValueError:
                    pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
    elapsed = time.time() - t0
    if data is None:
        try:
            data = ps3_elf.tty_to_bin(open(tty, errors="replace").read(), total)
        except (OSError, ValueError) as e:
            tail = open(log, errors="replace").read()[-3000:] if os.path.exists(log) else "(no RPCS3.log)"
            raise SystemExit(f"RPCS3 did not print the results ({e}). RPCS3.log tail:\n{tail}")
    with open(os.path.join(b, "rpcs3.bin"), "wb") as f:
        f.write(data)

    version = ""
    if os.path.exists(log):
        m = re.search(r"^\ufeff?(RPCS3 v\S+.*)$", open(log, encoding="utf-8", errors="replace").read(), re.M)
        version = m.group(1).strip() if m else ""

    qemu = open(os.path.join(b, "oracle.bin"), "rb").read()
    oracles = failing_set(meta, qemu, data)
    targets = {}
    for name, fn in (("host-" + os.uname().machine, "host.bin"), ("android-arm64 (qemu-aarch64)", "arm64.bin")):
        p = os.path.join(b, fn)
        if os.path.exists(p):
            targets[name] = failing_set(meta, data, open(p, "rb").read())

    with open(os.path.join(HERE, "known_divergences.json")) as f:
        known = json.load(f)

    def entry_of(case):
        c = meta["cases"][case]
        for e in known["entries"]:
            m = e["match"]
            if "groups" in m and c["group"] not in m["groups"]:
                continue
            if "name_regex" in m and not re.search(m["name_regex"], c["name"]):
                continue
            return e["id"]
        return None

    # For each known divergence (lifted != qemu), which side does RPCS3 take?
    host_name = next(iter(targets), None)
    lifted_vs_qemu = failing_set(meta, qemu, open(os.path.join(b, "arm64.bin" if os.path.exists(os.path.join(b, "arm64.bin")) else "host.bin"), "rb").read())
    verdict = collections.defaultdict(collections.Counter)
    for case in lifted_vs_qemu:
        eid = entry_of(case) or "(unexplained)"
        rpcs3_eq_qemu = case not in oracles
        rpcs3_eq_lifted = case not in targets.get("android-arm64 (qemu-aarch64)", targets.get(host_name, {}))
        verdict[eid]["rpcs3 = qemu" if rpcs3_eq_qemu else ("rpcs3 = lifted" if rpcs3_eq_lifted else "all three differ")] += 1

    by_group = collections.Counter(meta["cases"][c]["group"] for c in oracles)
    report = {
        "schema": "recomp_android.ppu-diff-rpcs3-report", "schema_version": 1,
        "rpcs3": version, "rpcs3_config": CONFIG_YML, "forced_hle_libraries": len(libs), "elapsed_s": round(elapsed, 1),
        "cases": meta["count"],
        "oracles_disagree": {"count": len(oracles), "by_group": dict(by_group.most_common()),
                             "samples": [oracles[k] for k in sorted(oracles)[:150]]},
        "lifted_vs_rpcs3": {t: {"failed": len(v), "by_group": dict(collections.Counter(
            meta["cases"][c]["group"] for c in v).most_common())} for t, v in targets.items()},
        "known_divergences_vs_rpcs3": {k: dict(v) for k, v in verdict.items()},
    }
    with open(os.path.join(b, "report_rpcs3.json"), "w") as f:
        json.dump(report, f, indent=1)
    print(f"RPCS3 run: {elapsed:.0f} s ({version or 'version not found in log'})")
    print(f"qemu vs RPCS3: {meta['count'] - len(oracles)}/{meta['count']} cases agree; disagree in: "
          + ", ".join(f"{g} {k}" for g, k in by_group.most_common(25)))
    for t, v in targets.items():
        print(f"{t} vs RPCS3: {meta['count'] - len(v)}/{meta['count']} match")
    for eid, v in sorted(verdict.items()):
        print(f"  {eid}: " + ", ".join(f"{k} {n}" for k, n in v.items()))
    print("report:", os.path.join(b, "report_rpcs3.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
