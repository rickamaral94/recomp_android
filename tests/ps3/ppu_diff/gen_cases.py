#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate the PPU differential-test kernel: PowerPC assembly + a case table.

Each case loads known inputs, runs one instruction (or a short sequence), then stores a
32-byte record to the output buffer (r3, 16-byte aligned, advanced per case). The layout
depends on the case kind:

  kind  +0..7          +8..15             +16  +20
  int   r7             r8                 CR   XER (low 32 bits)
  fp    f7 (bits)      f8 (bits)          CR   FPSCR (informational, see below)
  vmx   v7 (bytes 0-7) v7 (bytes 8-15)    CR   VSCR

int inputs: r4-r6, CR, XER. fp inputs: f1-f3, FPSCR (rounding mode). vmx inputs: v4-v6, VSCR
(NJ). Results are preset to sentinels. Bytes 24-31 are left zero.

FPSCR status bits are recorded but not compared: ps3recomp documents that its FP arithmetic
does not update FPSCR status yet (tools/ppu_lifter.py). FP record forms (Rc=1), whose CR1
comes from those bits, are left out for the same reason. Hardware estimates (fres,
frsqrte, vrefp, vrsqrtefp, vexptefp, vlogefp) are left out: their exact bits are
implementation-specific, so POWER7 says nothing about the Cell. Cell-only lvlx/lvrx/stvlx/
stvrx do not exist on POWER7 and need another oracle.

r9 holds the scratch-memory base for load/store cases; r31 is setup scratch. Cases are
grouped into functions of CHUNK cases (ppu_diff_chunk_N), called with `bl` from
ppu_diff_kernel, which keeps LR in r28: that also exercises direct calls and returns between
lifted functions. The kernel has no relocations and does not touch the stack, so the same
bytes run under qemu-ppc64 (the oracle) and through the lifter.

Fields the ISA leaves undefined are masked per case ("masks"), never compared:
the high word of 32-bit multiply-high/divide results in 64-bit mode, CR0 LT/GT/EQ when the
64-bit result is undefined, and divide results for division by zero or overflow.

Usage: gen_cases.py OUT_DIR [--suites int,fp,vmx]   -> OUT_DIR/kernel.S, OUT_DIR/cases.json
"""
import argparse
import json
import os
import random
import struct
import sys

M64 = (1 << 64) - 1
SENT7 = 0x5A5A5A5A5A5A5A5A
SENT8 = 0xA5A5A5A5A5A5A5A5
RECORD = 32
SCRATCH_SIZE = 256
TEMP = 0x400        # r9 + TEMP: staging area for FP/VMX constants (not compared)
SCRATCH_ALLOC = 0x800
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
        self.cases.append({"name": name, "kind": "int", "group": group or name.split()[0].rstrip(".o"),
                           "inputs": {"r4": f"{r4 & M64:#x}", "r5": f"{r5 & M64:#x}", "r6": f"{r6 & M64:#x}",
                                      "cr": f"{cr:#x}", "xer": f"{xer:#x}"},
                           "masks": {"r7": f"{mask7:#x}", "r8": f"{mask8:#x}", "cr": f"{cr_mask:#x}",
                                     "xer": "0xffffffff"}})

    def stage64(self, off, v):
        """Store a 64-bit constant at r9 + TEMP + off (big-endian), via r31."""
        self.lines += load64("31", v) + [f"std 31, {TEMP + off}(9)"]

    def fcase(self, name, body, f1=0, f2=0, f3=0, fpscr=0, cr=0, mask7=M64, mask8=M64,
              cr_mask=0xFFFFFFFF, group=None):
        idx = len(self.cases)
        self.lines.append(f"# case {idx}: {name}")
        for i, v in enumerate((f1, f2, f3, SENT7, SENT8, fpscr)):
            self.stage64(8 * i, v)
        self.lines += [f"lfd 1, {TEMP}(9)", f"lfd 2, {TEMP + 8}(9)", f"lfd 3, {TEMP + 16}(9)",
                       f"lfd 7, {TEMP + 24}(9)", f"lfd 8, {TEMP + 32}(9)", f"lfd 0, {TEMP + 40}(9)",
                       "mtfsf 0xff, 0"]
        self.lines += load64("31", cr) + ["mtcrf 0xff, 31"]
        self.lines += body if isinstance(body, list) else [body]
        self.lines += ["stfd 7, 0(3)", "stfd 8, 8(3)", "mfcr 31", "stw 31, 16(3)",
                       "mffs 0", f"stfd 0, {TEMP + 48}(9)", f"lwz 31, {TEMP + 52}(9)", "stw 31, 20(3)",
                       f"addi 3, 3, {RECORD}"]
        self.cases.append({"name": name, "kind": "fp", "group": group or name.split()[0],
                           "inputs": {"f1": f"{f1:#x}", "f2": f"{f2:#x}", "f3": f"{f3:#x}", "fpscr": f"{fpscr:#x}"},
                           "masks": {"r7": f"{mask7:#x}", "r8": f"{mask8:#x}", "cr": f"{cr_mask:#x}", "xer": "0x0"}})

    def vcase(self, name, body, v4=0, v5=0, v6=0, vscr=0, cr=0, mask_hi=M64, mask_lo=M64,
              cr_mask=0xFFFFFFFF, group=None, r4=None):
        """v4-v6 are 128-bit ints (byte 0 = most significant). v7 is preset to a sentinel."""
        idx = len(self.cases)
        self.lines.append(f"# case {idx}: {name}")
        M128 = (1 << 128) - 1
        vals = (v4 & M128, v5 & M128, v6 & M128, (SENT7 << 64) | SENT8, vscr & 0xFFFFFFFF)
        for i, v in enumerate(vals):
            self.stage64(16 * i, v >> 64)
            self.stage64(16 * i + 8, v & M64)
        for i, vr in enumerate((4, 5, 6, 7, 0)):
            self.lines += [f"li 31, {TEMP + 16 * i}", f"lvx {vr}, 9, 31"]
        self.lines += ["mtvscr 0"]
        self.lines += load64("31", cr) + ["mtcrf 0xff, 31"]
        if r4 is not None:
            self.lines += load64("4", r4)
        self.lines += body if isinstance(body, list) else [body]
        self.lines += ["stvx 7, 0, 3", "mfcr 31", "stw 31, 16(3)",
                       "mfvscr 0", f"li 31, {TEMP + 96}", "stvx 0, 9, 31", f"lwz 31, {TEMP + 108}(9)",
                       "stw 31, 20(3)", f"addi 3, 3, {RECORD}"]
        self.cases.append({"name": name, "kind": "vmx", "group": group or name.split()[0],
                           "inputs": {"v4": f"{vals[0]:#034x}", "v5": f"{vals[1]:#034x}", "v6": f"{vals[2]:#034x}",
                                      "vscr": f"{vscr:#x}"},
                           "masks": {"r7": f"{mask_hi:#x}", "r8": f"{mask_lo:#x}", "cr": f"{cr_mask:#x}",
                                     "xer": "0xffffffff"}})

    def fresh(self):
        self.label += 1
        return f".Lc{self.label}"


def xer_variants(carry_ops):
    return [0, XER_CA, XER_SO, XER_SO | XER_CA] if carry_ops else [0, XER_SO]


def build_int(g):
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


# ---------------------------------------------------------------------------------------------
# Floating point
# ---------------------------------------------------------------------------------------------

def dbits(x):
    return struct.unpack(">Q", struct.pack(">d", x))[0]


QNAN, SNAN = 0x7FF8000000000000, 0x7FF0000000000001
FP_ALL = [0, 0x8000000000000000, dbits(1.0), dbits(-1.0), dbits(1.5), dbits(3.0), dbits(0.1),
          dbits(1 / 3), 0x7FEFFFFFFFFFFFFF, 0x0010000000000000, 1, 0x800FFFFFFFFFFFFF,
          0x7FF0000000000000, 0xFFF0000000000000, QNAN, 0x7FF8000000000123, 0xFFF8000000000456,
          SNAN, 0x7FF4000000000ABC, dbits(2.0 ** 31), dbits(-2.0 ** 31 - 1), dbits(4294967296.5),
          dbits(1e39), dbits(1e-40), dbits(1 + 2 ** -30), dbits(-2.5), dbits(2.0 ** 63), dbits(-2.0 ** 63)]
FP_PAIR = [0, 0x8000000000000000, dbits(1.0), dbits(-1.5), dbits(0.1), dbits(1 / 3), 0x7FEFFFFFFFFFFFFF,
           1, 0x7FF0000000000000, 0xFFF0000000000000, 0x7FF8000000000123, SNAN, dbits(1e39),
           dbits(1 + 2 ** -30)]
FP_TRIPLE = [0, dbits(1.0), dbits(-0.1), dbits(1 / 3), 0x7FF0000000000000, 0x7FF8000000000123, 1]
FP_SINGLE = [0, 0x80000000, 0x3F800000, 0x00000001, 0x807FFFFF, 0x7F7FFFFF, 0x7F800000,
             0xFF800000, 0x7FC00000, 0x7F800001, 0x7FA00123]
RN = {0: "nearest", 1: "toward zero", 2: "toward +inf", 3: "toward -inf"}


def build_fp(g):
    LO32 = 0xFFFFFFFF
    for op in ("fadd", "fsub", "fmul", "fdiv", "fadds", "fsubs", "fmuls", "fdivs"):
        for a in FP_PAIR:
            for b in FP_PAIR:
                g.fcase(f"{op} f7,f1,f2", f"{op} 7, 1, 2", f1=a, f2=b, group=op)
    for op in ("fmadd", "fmsub", "fnmadd", "fnmsub", "fmadds", "fmsubs", "fnmadds", "fnmsubs", "fsel"):
        for a in FP_TRIPLE:
            for c in FP_TRIPLE:
                for b in FP_TRIPLE:
                    g.fcase(f"{op} f7,f1,f2,f3", f"{op} 7, 1, 2, 3", f1=a, f2=c, f3=b, group=op)
    for op in ("fabs", "fnabs", "fneg", "fmr", "frsp", "fsqrt", "fsqrts", "fctiw", "fctiwz",
               "fctid", "fctidz", "fcfid"):
        for a in FP_ALL + ([0x7FFFFFFFFFFFFFFF, 0x8000000000000000, 1, 0xFFFFFFFFFFFFFFFF, 0x0020000000000001]
                           if op == "fcfid" else []):
            # fctiw/fctiwz: FRT[0:31] are undefined (Book I 4.6.7)
            m = LO32 if op in ("fctiw", "fctiwz") else M64
            g.fcase(f"{op} f7,f1", f"{op} 7, 1", f1=a, mask7=m, group=op)
    for op in ("fcmpu", "fcmpo"):
        for a in FP_PAIR:
            for b in FP_PAIR:
                g.fcase(f"{op} cr1,f1,f2", f"{op} 1, 1, 2", f1=a, f2=b, cr=0xFFFFFFFF, group=op)
    # Rounding modes (FPSCR[RN]) on inexact operations.
    inexact = [(dbits(0.1), dbits(0.2)), (dbits(1 / 3), dbits(3.0)), (dbits(1 + 2 ** -30), dbits(1.0)),
               (dbits(-0.1), dbits(-0.7)), (dbits(2.5), dbits(1.0)), (dbits(-2.5), dbits(1.0))]
    for rn in (1, 2, 3):
        for a, b in inexact:
            for op in ("fadd", "fmul", "fdiv", "fadds", "fmuls"):
                g.fcase(f"{op} f7,f1,f2 RN={rn}", f"{op} 7, 1, 2", f1=a, f2=b, fpscr=rn, group=f"{op} (RN)")
            g.fcase(f"fmadd f7,f1,f2,f3 RN={rn}", "fmadd 7, 1, 2, 3", f1=a, f2=b, f3=dbits(0.3), fpscr=rn,
                    group="fmadd (RN)")
            for op in ("frsp", "fctiw", "fctid"):
                g.fcase(f"{op} f7,f1 RN={rn}", f"{op} 7, 1", f1=a, fpscr=rn,
                        mask7=LO32 if op == "fctiw" else M64, group=f"{op} (RN)")
        for v in (0x7FFFFFFFFFFFFFFF, 0x0020000000000001, 0xFFFFFFFFFFFFFFFF):
            g.fcase(f"fcfid f7,f1 RN={rn}", "fcfid 7, 1", f1=v, fpscr=rn, group="fcfid (RN)")
    # Memory format conversions.
    T = TEMP + 64
    for sv in FP_SINGLE:
        g.fcase(f"lfs f7 <- {sv:#010x}", load64("31", sv << 32) + [f"std 31, {T}(9)", f"lfs 7, {T}(9)"],
                group="lfs")
    for dv in FP_ALL:
        g.fcase("stfs f1", [f"stfs 1, {T}(9)", "li 31, 0", f"stw 31, {T + 4}(9)", f"lfd 8, {T}(9)"],
                f1=dv, group="stfs")
        g.fcase("fctiwz+stfiwx f1", ["fctiwz 7, 1", f"li 31, {T}", "stfiwx 7, 9, 31", "li 31, 0",
                                     f"stw 31, {T + 4}(9)", f"lfd 8, {T}(9)"],
                f1=dv, mask7=LO32, group="stfiwx")
        g.fcase("stfd/lfd round trip f1", [f"stfd 1, {T}(9)", f"lfd 7, {T}(9)", f"li 31, {T}", "lfdx 8, 9, 31"],
                f1=dv, group="stfd/lfd")


# ---------------------------------------------------------------------------------------------
# VMX / AltiVec
# ---------------------------------------------------------------------------------------------

VSCR_NJ, VSCR_SAT = 0x00010000, 0x00000001


def vwords(*w):
    v = 0
    for x in w:
        v = (v << 32) | (x & 0xFFFFFFFF)
    return v


def fw(x):
    return struct.unpack(">I", struct.pack(">f", x))[0]


VI = [0, (1 << 128) - 1, int.from_bytes(bytes(range(16)), "big"),
      0x7F80FF00017E80817FFF8000FFFF0001, vwords(0x7FFFFFFF, 0x80000000, 1, 0xFFFFFFFF),
      0x7FFF80000001FFFF00007FFE8001FFFE, rng.getrandbits(128), rng.getrandbits(128)]
VI6 = VI[:6]
VF = [vwords(fw(0.0), fw(-0.0), fw(1.0), fw(-1.0)),
      vwords(0x7F800000, 0xFF800000, 0x7FC00000, 0x7F800001),
      vwords(0x00000001, 0x80400000, 0x00800000, 0x7F7FFFFF),
      vwords(fw(1.5), 0x4F000000, fw(-2.5), fw(1e10)),
      vwords(fw(0.1), fw(1 / 3), fw(3.0), fw(-0.75)),
      vwords(0x7FC00123, 0xFFC00000, 0x3F7FFFFF, 0x33800000)]
PERM = [int.from_bytes(bytes(range(16)), "big"), int.from_bytes(bytes(range(31, 15, -1)), "big"),
        int.from_bytes(bytes([(i * 7) & 0x1F for i in range(16)]), "big"),
        int.from_bytes(bytes([0xE0 | (i * 3 & 0x1F) for i in range(16)]), "big")]

V_BIN = ("vaddubm vadduhm vadduwm vaddubs vadduhs vadduws vaddsbs vaddshs vaddsws vaddcuw "
         "vsububm vsubuhm vsubuwm vsububs vsubuhs vsubuws vsubsbs vsubshs vsubsws vsubcuw "
         "vmuleub vmuleuh vmulesb vmulesh vmuloub vmulouh vmulosb vmulosh "
         "vavgub vavguh vavguw vavgsb vavgsh vavgsw vmaxub vmaxuh vmaxuw vmaxsb vmaxsh vmaxsw "
         "vminub vminuh vminuw vminsb vminsh vminsw vand vandc vor vnor vxor "
         "vslb vslh vslw vsrb vsrh vsrw vsrab vsrah vsraw vrlb vrlh vrlw vslo vsro "
         "vmrghb vmrghh vmrghw vmrglb vmrglh vmrglw "
         "vpkuhum vpkuwum vpkuhus vpkuwus vpkshus vpkswus vpkshss vpkswss vpkpx "
         "vsum4ubs vsum4sbs vsum4shs vsum2sws vsumsws").split()
V_CMP = "vcmpequb vcmpequh vcmpequw vcmpgtub vcmpgtuh vcmpgtuw vcmpgtsb vcmpgtsh vcmpgtsw".split()
V_FCMP = "vcmpeqfp vcmpgefp vcmpgtfp vcmpbfp".split()
V_TERN = "vsel vmsumubm vmsummbm vmsumuhm vmsumuhs vmsumshm vmsumshs vmhaddshs vmhraddshs vmladduhm".split()
V_FBIN = "vaddfp vsubfp vmaxfp vminfp".split()


def build_vmx(g):
    for op in V_BIN:
        for a in VI6:
            for b in VI6:
                g.vcase(f"{op} v7,v4,v5", f"{op} 7, 4, 5", v4=a, v5=b, group=op)
        # SAT is sticky: run once with it already set.
        g.vcase(f"{op} v7,v4,v5 [SAT in]", f"{op} 7, 4, 5", v4=VI[3], v5=VI[4], vscr=VSCR_SAT, group=op)
    # vsl/vsr: the ISA leaves the result undefined unless the low 3 bits of every byte of vB
    # are equal, so vB is a splatted shift count here.
    for op in ("vsl", "vsr"):
        for a in VI6:
            for sh in (0, 1, 3, 7):
                g.vcase(f"{op} v7,v4,v5 (sh={sh})", f"{op} 7, 4, 5", v4=a, v5=int.from_bytes(bytes([sh | 0x18] * 16), "big"),
                        group=op)
    for op in V_CMP:
        for sfx in ("", "."):
            for a in VI6:
                for b in VI6:
                    g.vcase(f"{op}{sfx} v7,v4,v5", f"{op}{sfx} 7, 4, 5", v4=a, v5=b, cr=0x12345678, group=op)
            g.vcase(f"{op}{sfx} v7,v4,v4", f"{op}{sfx} 7, 4, 4", v4=VI[6], cr=0x12345678, group=op)
    for op in V_TERN:
        for a in VI[:4]:
            for b in VI[2:6]:
                for c in (VI[0], VI[4], VI[6]):
                    g.vcase(f"{op} v7,v4,v5,v6", f"{op} 7, 4, 5, 6", v4=a, v5=b, v6=c, group=op)
    for c in PERM:
        for a, b in ((VI[2], VI[3]), (VI[6], VI[7])):
            g.vcase("vperm v7,v4,v5,v6", "vperm 7, 4, 5, 6", v4=a, v5=b, v6=c, group="vperm")
    for nj in (0, VSCR_NJ):
        tag = " [NJ]" if nj else ""
        for op in V_FBIN:
            for a in VF:
                for b in VF:
                    g.vcase(f"{op} v7,v4,v5{tag}", f"{op} 7, 4, 5", v4=a, v5=b, vscr=nj, group=op)
        for op in ("vmaddfp", "vnmsubfp"):
            for a in VF:
                for b in VF[::2]:
                    for c in VF[::3]:
                        g.vcase(f"{op} v7,v4,v5,v6{tag}", f"{op} 7, 4, 5, 6", v4=a, v5=b, v6=c, vscr=nj, group=op)
        for op in V_FCMP:
            for sfx in ("", "."):
                for a in VF:
                    for b in VF[:4]:
                        g.vcase(f"{op}{sfx} v7,v4,v5{tag}", f"{op}{sfx} 7, 4, 5", v4=a, v5=b, vscr=nj,
                                cr=0x12345678, group=op)
        for op in ("vrfin", "vrfiz", "vrfip", "vrfim"):
            for a in VF:
                g.vcase(f"{op} v7,v4{tag}", f"{op} 7, 4", v4=a, vscr=nj, group=op)
        for op in ("vctuxs", "vctsxs"):
            for u in (0, 1, 31):
                for a in VF:
                    g.vcase(f"{op} v7,v4,{u}{tag}", f"{op} 7, 4, {u}", v4=a, vscr=nj, group=op)
    for op in ("vcfux", "vcfsx"):
        for u in (0, 1, 31):
            for a in VI6:
                g.vcase(f"{op} v7,v4,{u}", f"{op} 7, 4, {u}", v4=a, group=op)
    for op in ("vupkhsb", "vupkhsh", "vupklsb", "vupklsh", "vupkhpx", "vupklpx"):
        for a in VI:
            g.vcase(f"{op} v7,v4", f"{op} 7, 4", v4=a, group=op)
    for op, us in (("vspltb", (0, 7, 15)), ("vsplth", (0, 3, 7)), ("vspltw", (0, 1, 2, 3))):
        for u in us:
            for a in (VI[2], VI[6]):
                g.vcase(f"{op} v7,v4,{u}", f"{op} 7, 4, {u}", v4=a, group=op)
    for op in ("vspltisb", "vspltish", "vspltisw"):
        for simm in (-16, -1, 0, 1, 15):
            g.vcase(f"{op} v7,{simm}", f"{op} 7, {simm}", group=op)
    for sh in (0, 1, 7, 8, 15):
        g.vcase(f"vsldoi v7,v4,v5,{sh}", f"vsldoi 7, 4, 5, {sh}", v4=VI[2], v5=VI[6], group="vsldoi")
    # Loads and stores. r4 = scratch + off; scratch holds bytes 0x10.. (stores land at +128..).
    base = 0x20000000
    for off in (0, 3, 8, 13):
        g.vcase(f"lvx v7,0,r4 (+{off})", "lvx 7, 0, 4", r4=base + off, group="lvx")
        g.vcase(f"lvsl v7,0,r4 (+{off})", "lvsl 7, 0, 4", r4=base + off, group="lvsl")
        g.vcase(f"lvsr v7,0,r4 (+{off})", "lvsr 7, 0, 4", r4=base + off, group="lvsr")
    for op, size in (("lvebx", 1), ("lvehx", 2), ("lvewx", 4)):
        for off in range(0, 16, size + (size == 1) * 2):
            ea = off & ~(size - 1)
            elem = ((1 << (8 * size)) - 1) << (8 * (16 - ea - size))   # only the loaded element is defined
            g.vcase(f"{op} v7,0,r4 (+{off})", f"{op} 7, 0, 4", r4=base + 32 + off,
                    mask_hi=elem >> 64, mask_lo=elem & M64, group=op)
    for op, size in (("stvebx", 1), ("stvehx", 2), ("stvewx", 4), ("stvx", 16)):
        for off in (0, 4, 9, 14):
            g.vcase(f"{op} v4,0,r4 (+{off})", [f"{op} 4, 0, 4", "lvx 7, 0, 4"], v4=VI[6], r4=base + 128 + 16 * (size // 4) + off,
                    group=op)
    for v in (VSCR_NJ, VSCR_SAT, VSCR_NJ | VSCR_SAT, 0):
        g.vcase(f"mtvscr/mfvscr {v:#x}", "vor 7, 0, 0", vscr=v, group="mtvscr/mfvscr")


SUITES = {"int": build_int, "fp": build_fp, "vmx": build_vmx}


def build(suites=("int", "fp", "vmx")):
    g = Gen()
    for s in suites:
        SUITES[s](g)
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
            "scratch_size": SCRATCH_SIZE, "scratch_alloc": SCRATCH_ALLOC, "sentinels": {"r7": f"{SENT7:#x}", "r8": f"{SENT8:#x}"},
            "count": len(g.cases), "chunk": CHUNK, "cases": g.cases}
    with open(os.path.join(out_dir, "cases.json"), "w") as f:
        json.dump(meta, f, indent=0)
    return len(g.cases)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate the PPU differential-test kernel")
    ap.add_argument("out_dir")
    ap.add_argument("--suites", default="int,fp,vmx", help="comma list of: " + ",".join(SUITES))
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    print(emit(build(a.suites.split(",")), a.out_dir), "cases")
