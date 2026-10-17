#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate a report.json against schema recomp_android.diagnostic-report v1.

Usage: check_report.py REPORT.json   (or a diagnostic ZIP: its report.json is checked)
Exit status 0 when valid; prints every problem otherwise.
"""
import json
import sys
import zipfile

LEVELS = ["none", "compiled", "installed", "opened", "profile_loaded",
          "reached_menu", "reached_gameplay", "stability_passed"]
TOP = {"schema", "schema_version", "generated_at", "build", "device", "vulkan", "game",
       "analysis", "recompilation", "metrics", "tests", "result", "limitations"}


def load(path):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            return json.loads(z.read("report.json").decode("utf-8"))
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check(r):
    errs = []
    missing = TOP - r.keys()
    if missing:
        errs.append(f"missing top-level keys: {sorted(missing)}")
    if r.get("schema") != "recomp_android.diagnostic-report":
        errs.append(f"bad schema: {r.get('schema')!r}")
    if r.get("schema_version") != 1:
        errs.append(f"bad schema_version: {r.get('schema_version')!r}")
    b = r.get("build", {})
    for k in ("commit", "version", "abi", "build_type", "compiler"):
        if not isinstance(b.get(k), str) or not b.get(k):
            errs.append(f"build.{k} must be a non-empty string")
    v = r.get("vulkan", {})
    if not isinstance(v.get("devices"), list):
        errs.append("vulkan.devices must be a list")
    if v.get("instance_created") is False and not v.get("error"):
        errs.append("vulkan.error must explain a failed probe")
    for d in v.get("devices", []):
        for k in ("name", "vendor_id", "api_version", "driver_version", "extensions"):
            if k not in d:
                errs.append(f"vulkan device missing {k}")
    # Unmeasured metrics must say so rather than carry numbers.
    for name, m in r.get("metrics", {}).items():
        if isinstance(m, dict) and m.get("collected") is False and not m.get("reason"):
            errs.append(f"metrics.{name}: not collected without a reason")
    level = r.get("result", {}).get("level")
    if level not in LEVELS:
        errs.append(f"result.level {level!r} not in {LEVELS}")
    for t in r.get("tests", []):
        if t.get("status") not in ("passed", "failed", "skipped"):
            errs.append(f"test {t.get('name')!r}: bad status {t.get('status')!r}")
    return errs


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    errs = check(load(sys.argv[1]))
    for e in errs:
        print("report.json:", e)
    if not errs:
        print("report.json: OK")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
