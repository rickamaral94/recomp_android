#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate the PPU differential-test kernel: PowerPC assembly + a case table.

Each case loads known inputs (r4-r6, CR, XER), runs one instruction (or a short sequence),
then stores a 24-byte record to the output buffer (r3, advanced per case):

  +0  r7  (primary result; preset to a sentinel)
  +8  r8  (secondary result: update-form RA, second destination, ...; preset to a sentinel)
  +16 CR  (mfcr)
  +20 XER (mfxer, low 32 bits)

r9 holds the scratch-memory base for load/store cases; r31 is setup scratch. Cases are
grouped into functions of CHUNK cases (ppu_diff_chunk_N), called with `bl` from
ppu_diff_kernel, which keeps LR in r28: that also exercises direct calls and returns between
lifted functions. The kernel has no relocations and does not touch the stack, so the same
bytes run under qemu-ppc64 (the oracle) and through the lifter.

Fields the ISA leaves undefined are masked per case ("masks"), never compared:
the high word of 32-bit multiply-high/divide results in 64-bit mode, CR0 LT/GT/EQ when the
64-bit result is undefined, and divide results for division by zero or overflow.

Usage: gen_cases.py OUT_DIR   -> OUT_DIR/kernel.S, OUT_DIR/cases.json
"""
import json
import os
import random
import sys

M64 = (1 << 64) - 1
SENT7 = 0x5A5A5A5A5A5A5A5A
SENT8 = 0xA5A5A5A5A5A5A5A5
RECORD = 24
SCRATCH_SIZE = 256
CHUNK = 250

XER_SO, XER_OV, XER_CA = 1 << 31, 1 << 30, 1 << 29

EDGE = [0, 1, 2, 0x7F, 0x80, 0xFF, 0x7FFF, 0x8000, 0xFFFF, 0x7FFFFFFF, 0x80000000,
        0xFFFFFFFF, 0x100000000, 0x7FFFFFFFFFFFFFFF, 0x8000000000000000, M64,
        0x123456789ABCDEF0, 0xFEDCBA9876543210, 0xFFFFFFFF80000000, 0x00000000FFFF0000]
SMALL = [0, 1, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 0x7FFFFFFFFFFFFFFF, 0x8000000000000000,
         M64, 0x123456789ABCDEF0]
SHIFTS = [0, 1, 7, 31, 32, 33, 63, 64, 65, 127, 0xFFFFFFFFFFFFFF80]

rng = random.Random(20261017)
RANDOM = [rng.getrandbits(64) for _ in range(6)]


def load64(reg, v):
    v &= M64
    return [f"lis {reg}, {(v >> 48) & 0xFFFF:#x}@l",  # @l keeps lis from range-checking
            f"ori {reg}, {reg}, {(v >> 32) & 0xFFFF:#x}",
            f"sldi {reg}, {reg}, 32",
            f"oris {reg}, {reg}, {(v >> 16) & 0xFFFF:#x}",
            f"ori {reg}, {reg}, {v & 0xFFFF:#x}"]


class Gen:
    def __init__(self):
        self.lines = []
        self.cases = []
        self.label = 0

    def case(self, name, body, r4=0, r5=0, r6=0, cr=0, xer=0, r8=SENT8,
             mask7=M64, mask8=M64, cr_mask=0xFFFFFFFF, group=None):
        # A record form (Rc=1) copies XER[SO] into CR0: run every such case with SO set too,
        # or a lift that drops that copy goes unnoticed.
        mnemonic = name.split()[0]
        if mnemonic.endswith(".") and not xer & XER_SO:
            self._case(name + " [SO]", body, r4, r5, r6, cr, xer | XER_SO, r8, mask7, mask8, cr_mask, group)
        self._case(name, body, r4, r5, r6, cr, xer, r8, mask7, mask8, cr_mask, group)

    def _case(self, name, body, r4, r5, r6, cr, xer, r8, mask7, mask8, cr_mask, group):
        idx = len(self.cases)
        self.lines.append(f"# case {idx}: {name}")
        for reg, v in (("4", r4), ("5", r5), ("6", r6), ("7", SENT7), ("8", r8)):
            self.lines += load64(reg, v)
        self.lines += load64("31", cr) + ["mtcrf 0xff, 31"]
        self.lines += load64("31", xer) + ["mtxer 31"]
        self.lines += body if isinstance(body, list) else [body]
        self.lines += ["std 7, 0(3)", "std 8, 8(3)", "mfcr 31", "stw 31, 16(3)",
                       "mfxer 31", "stw 31, 20(3)", f"addi 3, 3, {RECORD}"]
        self.cases.append({"name": name, "group": group or name.split()[0].rstrip(".o"),
                           "inputs": {"r4": f"{r4 & M64:#x}", "r5": f"{r5 & M64:#x}", "r6": f"{r6 & M64:#x}",
                                      "cr": f"{cr:#x}", "xer": f"{xer:#x}"},
                           "masks": {"r7": f"{mask7:#x}", "r8": f"{mask8:#x}", "cr": f"{cr_mask:#x}"}})

    def fresh(self):
        self.label += 1
        return f".Lc{self.label}"


def xer_variants(carry_ops):
    return [0, XER_CA, XER_SO, XER_SO | XER_CA] if carry_ops else [0, XER_SO]


def build():
    g = Gen()
    LO32 = 0xFFFFFFFF
    CR0_SO_ONLY = 0x1FFFFFFF  # CR0 LT/GT/EQ undefined, SO still defined

    # --- add/sub family (XO-form), with and without OE and Rc ---
    xo = {"add": False, "addc": True, "adde": True, "subf": False, "subfc": True, "subfe": True}
    for op, carry in xo.items():
        for sfx in ("", ".", "o", "o."):
            for a in (EDGE if sfx == "" else SMALL):
                for b in SMALL:
                    for x in (xer_variants(carry) if sfx in ("o", "o.") else [0, XER_CA] if carry else [0]):
                        g.case(f"{op}{sfx} r7,r4,r5", f"{op}{sfx} 7, 4, 5", r4=a, r5=b, xer=x, group=op)
    for op in ("addze", "addme", "subfze", "subfme", "neg"):
        for sfx in ("", ".", "o", "o."):
            for a in EDGE:
                for x in xer_variants(op != "neg"):
                    g.case(f"{op}{sfx} r7,r4", f"{op}{sfx} 7, 4", r4=a, xer=x, group=op)
    for imm in (0, 1, -1, 0x7FFF, -0x8000):
        for a in EDGE:
            for x in (0, XER_CA):
                g.case(f"addic r7,r4,{imm}", f"addic 7, 4, {imm}", r4=a, xer=x, group="addic")
                g.case(f"addic. r7,r4,{imm}", f"addic. 7, 4, {imm}", r4=a, xer=x, group="addic.")
                g.case(f"subfic r7,r4,{imm}", f"subfic 7, 4, {imm}", r4=a, xer=x, group="subfic")
            g.case(f"addi r7,r4,{imm}", f"addi 7, 4, {imm}", r4=a, group="addi")
            g.case(f"addis r7,r4,{imm}", f"addis 7, 4, {imm}", r4=a, group="addis")
            g.case(f"mulli r7,r4,{imm}", f"mulli 7, 4, {imm}", r4=a, group="mulli")

    # --- multiply / divide ---
    for op, m7, crm in (("mullw", M64, None), ("mulhw", LO32, CR0_SO_ONLY), ("mulhwu", LO32, CR0_SO_ONLY),
                        ("mulld", M64, None), ("mulhd", M64, None), ("mulhdu", M64, None)):
        sfxs = ("", ".", "o", "o.") if op in ("mullw", "mulld") else ("", ".")
        for sfx in sfxs:
            for a in SMALL + RANDOM[:2]:
                for b in SMALL:
                    g.case(f"{op}{sfx} r7,r4,r5", f"{op}{sfx} 7, 4, 5", r4=a, r5=b, xer=XER_SO if "o" in sfx else 0,
                           mask7=m7, cr_mask=(crm if (crm and "." in sfx) else 0xFFFFFFFF), group=op)
    for op, word, signed in (("divw", True, True), ("divwu", True, False), ("divd", False, True), ("divdu", False, False)):
        for sfx in ("", ".", "o", "o."):
            for a in SMALL + [7, 0xFFFFFFF9]:
                for b in SMALL + [2, 3, 0xFFFFFFFE]:
                    bb = b & (LO32 if word else M64)
                    aa = a & (LO32 if word else M64)
                    if signed:
                        sa = aa - (1 << (32 if word else 64)) if aa >> ((32 if word else 64) - 1) else aa
                        sb = bb - (1 << (32 if word else 64)) if bb >> ((32 if word else 64) - 1) else bb
                        undefined = sb == 0 or (sb == -1 and sa == -(1 << ((32 if word else 64) - 1)))
                    else:
                        undefined = bb == 0
                    m7 = 0 if undefined else (LO32 if word else M64)
                    crm = 0xFFFFFFFF
                    if "." in sfx and (undefined or word):
                        crm = CR0_SO_ONLY  # word divide in 64-bit mode: CR0 LT/GT/EQ undefined
                    g.case(f"{op}{sfx} r7,r4,r5", f"{op}{sfx} 7, 4, 5", r4=a, r5=b, xer=0,
                           mask7=m7, cr_mask=crm, group=op)

    # --- logical ---
    for op in ("and", "or", "xor", "nand", "nor", "eqv", "andc", "orc"):
        for sfx in ("", "."):
            for a in SMALL:
                for b in SMALL[::2] + RANDOM[2:4]:
                    g.case(f"{op}{sfx} r7,r4,r5", f"{op}{sfx} 7, 4, 5", r4=a, r5=b, xer=XER_SO, group=op)
    for op in ("andi.", "andis.", "ori", "oris", "xori", "xoris"):
        for imm in (0, 1, 0x8000, 0xFFFF, 0x1234):
            for a in EDGE:
                g.case(f"{op} r7,r4,{imm:#x}", f"{op} 7, 4, {imm:#x}", r4=a, group=op)
    for op in ("extsb", "extsh", "extsw", "cntlzw", "cntlzd"):
        for sfx in ("", "."):
            for a in EDGE + RANDOM:
                g.case(f"{op}{sfx} r7,r4", f"{op}{sfx} 7, 4", r4=a, group=op)

    # --- shifts and rotates ---
    for op in ("slw", "srw", "sraw", "sld", "srd", "srad"):
        for sfx in ("", "."):
            for a in SMALL + RANDOM[:2]:
                for s in SHIFTS:
                    g.case(f"{op}{sfx} r7,r4,r5", f"{op}{sfx} 7, 4, 5", r4=a, r5=s, xer=XER_CA, group=op)
    for sh in (0, 1, 5, 31):
        for a in SMALL + RANDOM[:2]:
            g.case(f"srawi r7,r4,{sh}", f"srawi 7, 4, {sh}", r4=a, xer=XER_CA, group="srawi")
    for sh in (0, 1, 31, 32, 63):
        for a in SMALL + RANDOM[:2]:
            g.case(f"sradi r7,r4,{sh}", f"sradi 7, 4, {sh}", r4=a, xer=XER_CA, group="sradi")
    for sh, mb, me in ((0, 0, 31), (1, 0, 30), (8, 24, 31), (16, 16, 15), (31, 31, 31), (4, 28, 3), (0, 16, 31)):
        for a in SMALL + RANDOM[:3]:
            g.case(f"rlwinm r7,r4,{sh},{mb},{me}", f"rlwinm 7, 4, {sh}, {mb}, {me}", r4=a, group="rlwinm")
            g.case(f"rlwinm. r7,r4,{sh},{mb},{me}", f"rlwinm. 7, 4, {sh}, {mb}, {me}", r4=a, group="rlwinm.")
            g.case(f"rlwimi r7,r4,{sh},{mb},{me}", ["mr 7, 5", f"rlwimi 7, 4, {sh}, {mb}, {me}"],
                   r4=a, r5=RANDOM[5], group="rlwimi")
        for s in (0, 1, 31, 32, 63):
            g.case(f"rlwnm r7,r4,r5,{mb},{me}", f"rlwnm 7, 4, 5, {mb}, {me}", r4=RANDOM[0], r5=s, group="rlwnm")
    for sh, mb in ((0, 0), (1, 0), (32, 32), (63, 63), (4, 60), (0, 48)):
        for a in SMALL + RANDOM[:3]:
            for op in ("rldicl", "rldicr", "rldic"):
                g.case(f"{op} r7,r4,{sh},{mb}", f"{op} 7, 4, {sh}, {mb}", r4=a, group=op)
            g.case(f"rldimi r7,r4,{sh},{mb}", ["mr 7, 5", f"rldimi 7, 4, {sh}, {mb}"],
                   r4=a, r5=RANDOM[4], group="rldimi")
        for s in (0, 1, 63, 64):
            g.case(f"rldcl r7,r4,r5,{mb}", f"rldcl 7, 4, 5, {mb}", r4=RANDOM[1], r5=s, group="rldcl")
            g.case(f"rldcr r7,r4,r5,{mb}", f"rldcr 7, 4, 5, {mb}", r4=RANDOM[1], r5=s, group="rldcr")

    # --- compares into several CR fields, with SO set and clear ---
    for op in ("cmpw", "cmplw", "cmpd", "cmpld"):
        for bf in (0, 3, 7):
            for a in SMALL:
                for b in SMALL:
                    for x in (0, XER_SO):
                        g.case(f"{op} cr{bf},r4,r5", f"{op} {bf}, 4, 5", r4=a, r5=b, xer=x, cr=0x12345678, group=op)
    for op, imms in (("cmpwi", (0, 1, -1, 0x7FFF, -0x8000)), ("cmplwi", (0, 1, 0xFFFF)),
                     ("cmpdi", (0, 1, -1)), ("cmpldi", (0, 1, 0xFFFF))):
        for imm in imms:
            for a in SMALL:
                g.case(f"{op} cr1,r4,{imm}", f"{op} 1, 4, {imm}", r4=a, cr=0xFFFFFFFF, group=op)

    # --- CR logical, mcrf, mtcrf, mfocrf ---
    crs = (0x00000000, 0xFFFFFFFF, 0x5A5AA5A5, 0x13579BDF)
    for op in ("crand", "cror", "crxor", "crnand", "crnor", "creqv", "crandc", "crorc"):
        for c in crs:
            for bt, ba, bb in ((0, 1, 2), (31, 0, 31), (5, 9, 13), (16, 16, 16)):
                g.case(f"{op} {bt},{ba},{bb}", f"{op} {bt}, {ba}, {bb}", cr=c, group=op)
    for c in crs:
        for d, s in ((0, 7), (7, 0), (3, 3), (5, 2)):
            g.case(f"mcrf cr{d},cr{s}", f"mcrf {d}, {s}", cr=c, group="mcrf")
        for fxm in (0x01, 0x80, 0x5A, 0xFF):
            g.case(f"mtcrf {fxm:#x},r4", f"mtcrf {fxm:#x}, 4", r4=RANDOM[3], cr=c, group="mtcrf")

    # --- loads/stores: endianness, sign extension, update forms, byte reversal, misalignment ---
    # Scratch is filled with a pattern (bytes 0x10..0x10F) at kernel entry; r4 = r9 + offset.
    def mem(name, body, off, r5=0, group=None):
        g.case(name, [f"addi 4, 9, {off}"] + body, r5=r5, group=group, mask8=M64)
    for off in (0, 1, 2, 3, 6, 7):
        for op in ("lbz", "lhz", "lha", "lwz", "lwa", "ld"):
            if op in ("lwa", "ld") and off % 4:
                continue  # DS-form displacement must be a multiple of 4; misaligned EA comes from r4
            mem(f"{op} r7,{off}(r4)", [f"{op} 7, 0(4)"] if op not in ("lwa", "ld") else [f"{op} 7, 0(4)"],
                off, group=op)
        for op in ("lhbrx", "lwbrx", "ldbrx", "lbzx", "lhzx", "lhax", "lwzx", "lwax", "ldx"):
            mem(f"{op} r7,r4,r5 (+{off})", [f"{op} 7, 4, 5"], 0, r5=off + 16, group=op)
    for off in (8, 16, 33):
        for op in ("lbzu", "lhzu", "lhau", "lwzu"):
            mem(f"{op} r7,4(r4) (+{off})", [f"{op} 7, 4(4)", "mr 8, 4", "subf 8, 9, 8"], off, group=op)
        mem(f"ldu r7,8(r4) (+{off})", ["ldu 7, 8(4)", "mr 8, 4", "subf 8, 9, 8"], off - (off % 4), group="ldu")
    for off in (64, 65, 70):
        for op, n in (("stb", 1), ("sth", 2), ("stw", 4), ("std", 8)):
            if op == "std" and off % 4:
                continue
            mem(f"{op} (+{off})", load64("7", RANDOM[0]) + [f"{op} 7, 0(4)", "ld 7, 0(4)" if off % 8 == 0 else "lwz 7, 0(4)",
                                                           "addi 8, 9, 64", "ld 8, 0(8)"], off, group=op)
        for op in ("sthbrx", "stwbrx", "stdbrx"):
            mem(f"{op} (+{off})", load64("7", RANDOM[1]) + [f"{op} 7, 0, 4", "addi 8, 9, 64", "ld 7, 0(8)",
                                                           "ld 8, 8(8)"], off, group=op)
    for off in (96, 100):
        mem(f"stwu (+{off})", load64("7", RANDOM[2]) + ["stwu 7, 4(4)", "mr 8, 4", "subf 8, 9, 8", "lwz 7, 0(4)"],
            off, group="stwu")
        mem(f"stdu (+{off})", load64("7", RANDOM[3]) + ["stdu 7, 8(4)", "mr 8, 4", "subf 8, 9, 8", "ld 7, 0(4)"],
            off, group="stdu")

    # --- branches: CTR loops, conditional branches on each CR bit, bclr/bcctr not (needs calls) ---
    for n in (1, 2, 5, 17):
        l1 = g.fresh()
        g.case(f"bdnz loop x{n}", [f"li 31, {n}", "mtctr 31", "li 7, 0", f"{l1}:", "addi 7, 7, 3", f"bdnz {l1}",
                                    "mfctr 8"], group="bdnz")
    for c in (0x80000000, 0x40000000, 0x20000000, 0x10000000, 0x00000000, 0x0F000000):
        for bo, cond in (("blt", "lt"), ("bgt", "gt"), ("beq", "eq"), ("bso", "so"),
                         ("bge", "ge"), ("ble", "le"), ("bne", "ne"), ("bns", "ns")):
            l1 = g.fresh()
            g.case(f"{bo} cr0 (cr={c:#x})", ["li 7, 1", f"{bo} 0, {l1}", "li 7, 2", f"{l1}:"], cr=c, group="bc")
            l2 = g.fresh()
            g.case(f"{bo} cr1 (cr={c >> 4:#x})", ["li 7, 1", f"{bo} 1, {l2}", "li 7, 2", f"{l2}:"],
                   cr=c >> 4, group="bc")
    for n, cnd in ((1, "bdz"), (2, "bdz"), (1, "bdnzt"), (3, "bdnzf")):
        l1 = g.fresh()
        body = [f"li 31, {n}", "mtctr 31", "li 7, 0"]
        if cnd == "bdz":
            body += [f"{l1}:", "addi 7, 7, 1", f"bdz {l1}x", f"b {l1}", f"{l1}x:"]
        elif cnd == "bdnzt":
            body += [f"{l1}:", "addi 7, 7, 1", f"bdnzt 2, {l1}"]
        else:
            body += [f"{l1}:", "addi 7, 7, 1", f"bdnzf 2, {l1}"]
        g.case(f"{cnd} ctr={n}", body + ["mfctr 8"], cr=0x20000000, group=cnd)
    return g


def emit(g, out_dir):
    head = [
        "# Generated by tests/ps3/ppu_diff/gen_cases.py -- do not edit.",
        "    .abiversion 2",
        "    .text",
        "    .p2align 4",
        "    .globl ppu_diff_kernel",
        "ppu_diff_kernel:",
        "# r3 = output buffer, r9 = scratch base. Fill scratch with bytes 0x10, 0x11, ...",
        "    mflr 28",
        "    li 31, 0",
        "    li 30, 0x10",
        f"    li 29, {SCRATCH_SIZE}",
        "    mtctr 29",
        ".Lfill:",
        "    stbx 30, 9, 31",
        "    addi 30, 30, 1",
        "    addi 31, 31, 1",
        "    bdnz .Lfill",
    ]
    # Split the case lines at case boundaries into chunk functions.
    chunks, cur, count = [], [], 0
    for line in g.lines:
        if line.startswith("# case "):
            if count and count % CHUNK == 0:
                chunks.append(cur)
                cur = []
            count += 1
        cur.append(line)
    if cur:
        chunks.append(cur)
    head += [f"    bl ppu_diff_chunk_{i}" for i in range(len(chunks))]
    head += ["    mtlr 28", "    blr"]
    body = []
    for i, ch in enumerate(chunks):
        # Local symbols: a global one would leave every `bl` as an unresolved relocation.
        body += ["    .p2align 4", f"ppu_diff_chunk_{i}:"]
        body += ["    " + l if not l.endswith(":") and not l.startswith("#") else l for l in ch]
        body += ["    blr"]
    with open(os.path.join(out_dir, "kernel.S"), "w") as f:
        f.write("\n".join(head + body + [""]))
    meta = {"schema": "recomp_android.ppu-diff-cases", "schema_version": 1, "record_size": RECORD,
            "scratch_size": SCRATCH_SIZE, "sentinels": {"r7": f"{SENT7:#x}", "r8": f"{SENT8:#x}"},
            "count": len(g.cases), "chunk": CHUNK, "cases": g.cases}
    with open(os.path.join(out_dir, "cases.json"), "w") as f:
        json.dump(meta, f, indent=0)
    return len(g.cases)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    os.makedirs(sys.argv[1], exist_ok=True)
    print(emit(build(), sys.argv[1]), "cases")
