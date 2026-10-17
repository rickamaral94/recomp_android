#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Cross the imports of a game (from parse_rpcs3_log.py) with an HLE runtime's source tree.

Usage:
  hle_coverage.py FACTS.json RUNTIME_SRC [--label NAME] [-o OUT.json]

Each imported function (and each syscall seen in the game's syscall usage) lands in one of:
  defined    RUNTIME_SRC has a C/C++ definition with that exact name;
  mentioned  the name only appears as an identifier (registered through a table or macro,
             a prototype, a comment) -- needs a manual look;
  absent     the name does not appear at all.
None of this says the implementation is complete or correct: it is a map of where to look.
"""
import argparse
import json
import os
import re
import sys

DEF = re.compile(r"^[A-Za-z_][\w\s\*:<>,]*?\b([A-Za-z_]\w*)\s*\((.*)$")
SKIP_WORDS = {"if", "while", "for", "switch", "return", "sizeof", "else"}


IDENT = re.compile(r"[A-Za-z_]\w*")


def scan(root):
    """Return ({name: first definition}, {name: first mention}) for C/C++ sources and headers."""
    names, mentions = {}, {}
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "third_party", "build", "tests")]
        for f in files:
            if not f.endswith((".c", ".cc", ".cpp", ".h", ".hpp", ".inc")):
                continue
            path = os.path.join(dirpath, f)
            is_source = not f.endswith((".h", ".hpp", ".inc"))
            with open(path, encoding="utf-8", errors="replace") as fh:
                for n, line in enumerate(fh, 1):
                    where = f"{os.path.relpath(path, root)}:{n}"
                    for ident in IDENT.findall(line):
                        mentions.setdefault(ident, where)
                    if not is_source:
                        continue
                    m = DEF.match(line)
                    if not m or m.group(1) in SKIP_WORDS:
                        continue
                    rest = m.group(2)
                    # A prototype ends in ';'. A definition either opens its body on this line
                    # (one-liners such as `int f(x) { return 0; }`) or continues on the next.
                    if ";" in rest and "{" not in rest.split(";", 1)[0]:
                        continue
                    names.setdefault(m.group(1), where)
    return names, mentions


def classify(name, names, mentions):
    if not name:
        return "absent", None
    if name in names:
        return "defined", names[name]
    if name in mentions:
        return "mentioned", mentions[name]
    return "absent", None


def coverage(facts, names, mentions):
    boot = max((b for lg in facts["logs"] for b in lg["boots"]), key=lambda b: sum(b["import_summary"].values()))
    modules = {}
    totals = {"defined": 0, "mentioned": 0, "absent": 0}
    for mod, data in boot["imports"].items():
        rows = []
        for fn in data["functions"]:
            status, where = classify(fn["name"], names, mentions)
            rows.append({"name": fn["name"], "nid": fn["nid"], "status": status, "at": where})
            totals[status] += 1
        modules[mod] = {"imported": len(rows),
                        **{k: sum(1 for r in rows if r["status"] == k) for k in totals},
                        "absent_names": [r["name"] or r["nid"] for r in rows if r["status"] == "absent"],
                        "functions": rows}
    sys_rows = []
    usage = (boot.get("syscall_usage") or {}).get("counts", {})
    for name, count in sorted(usage.items(), key=lambda kv: -kv[1]):
        status, where = classify(name, names, mentions)
        sys_rows.append({"name": name, "calls": count, "status": status, "at": where})
    return {
        "ppu_hash": (boot.get("ppu_hash") or {}).get("value"),
        "serial": boot.get("serial"),
        "imports_total": sum(totals.values()),
        "imports": totals,
        "modules": modules,
        "syscalls_seen": len(sys_rows),
        "syscalls": {k: sum(1 for r in sys_rows if r["status"] == k) for k in totals},
        "syscall_rows": sys_rows,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("facts")
    ap.add_argument("runtime_src")
    ap.add_argument("--label", default="runtime")
    ap.add_argument("-o", "--output")
    a = ap.parse_args(argv)
    with open(a.facts, encoding="utf-8") as f:
        facts = json.load(f)
    result = {"schema": "recomp_android.hle-coverage", "schema_version": 1, "runtime": a.label,
              "criterion": "name match in source (defined / mentioned / absent); not a correctness claim"}
    result.update(coverage(facts, *scan(a.runtime_src)))
    text = json.dumps(result, indent=1, ensure_ascii=False) + "\n"
    if a.output:
        with open(a.output, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
