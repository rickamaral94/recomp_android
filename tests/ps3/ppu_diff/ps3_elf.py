#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Wrap the differential-test kernel in a PS3 executable (ELF64 BE PPC, ET_EXEC) for RPCS3.

The program runs the kernel, then prints every result byte (records, then the 256 scratch bytes)
as lowercase hex through sys_tty_write (syscall 403), in lines of LINE_BYTES bytes framed as
"@@<offset hex> <hex>\\n", and exits with sys_process_exit (22). RPCS3 copies TTY output to
TTY.log, which tty_to_bin() turns back into the same layout as oracle.bin.

Layout: code (stub + kernel) at 0x10000, flags 0x400005 (PPU R+X); data at DATA_BASE,
flags 0x600006 (PPU R+W): OPD of the entry, hex digits, sys_process_param, output buffer,
scratch, line buffer. The stub uses only syscalls, no PRX imports, so no firmware is needed.

Usage: ps3_elf.py KERNEL_BIN CASES_JSON OUT_ELF
"""
import json
import struct
import sys

CODE_BASE = 0x10000
DATA_BASE = 0x01000000
LINE_BYTES = 1024
SYS_PROCESS_PARAM_MAGIC = 0x13BCC5F6


STUB_S = """\
    .abiversion 2
    .text
    .globl _start
_start:
    lis 3, {OUT}@h
    ori 3, 3, {OUT}@l
    lis 9, {SCRATCH}@h
    ori 9, 9, {SCRATCH}@l
    bl kernel
    # Print records (region 0), then the scratch (region 1). r22 = running output offset.
    lis 20, {OUT}@h
    ori 20, 20, {OUT}@l
    lis 21, {N}@h
    ori 21, 21, {N}@l
    li 22, 0
    lis 24, {DIGITS}@h
    ori 24, 24, {DIGITS}@l
    li 25, 0
.Lline:
    lis 23, {LINE}@h
    ori 23, 23, {LINE}@l
    li 26, 0x40
    stb 26, 0(23)
    stb 26, 1(23)
    addi 23, 23, 2
    li 27, 8               # 8 hex digits of the offset, most significant first
    mtctr 27
    mr 30, 22
.Lhdr:
    rlwinm 26, 30, 4, 28, 31
    lbzx 26, 24, 26
    stb 26, 0(23)
    addi 23, 23, 1
    rlwinm 30, 30, 4, 0, 31
    bdnz .Lhdr
    li 26, 0x20
    stb 26, 0(23)
    addi 23, 23, 1
    li 27, {LINE_BYTES}    # n = min(left, LINE_BYTES)
    cmpdi 21, {LINE_BYTES}
    bgt .Lfull
    mr 27, 21
.Lfull:
    mtctr 27
.Lbyte:
    lbz 26, 0(20)
    addi 20, 20, 1
    rlwinm 28, 26, 28, 28, 31
    rlwinm 29, 26, 0, 28, 31
    lbzx 28, 24, 28
    lbzx 29, 24, 29
    stb 28, 0(23)
    stb 29, 1(23)
    addi 23, 23, 2
    bdnz .Lbyte
    li 26, 0x0a
    stb 26, 0(23)
    addi 23, 23, 1
    li 3, {TTY_FD}         # PS3: sys_tty_write(ch 0, LINE, len, PWLEN); linux: write(1, LINE, len)
    lis 4, {LINE}@h
    ori 4, 4, {LINE}@l
    subf 5, 4, 23
    lis 6, {PWLEN}@h
    ori 6, 6, {PWLEN}@l
    li {SYSREG}, {SYS_WRITE}
    sc
    add 22, 22, 27
    subf 21, 27, 21
    cmpdi 21, 0
    bne .Lline
    cmpdi 25, 0
    bne .Lexit
    li 25, 1
    lis 20, {SCRATCH}@h
    ori 20, 20, {SCRATCH}@l
    li 21, {SCRATCH_SIZE}
    b .Lline
.Lexit:
    li 3, 0                # PS3: sys_process_exit(0); linux: exit(0)
    li {SYSREG}, {SYS_EXIT}
    sc
    b .
    .p2align 4
kernel:
    .incbin "{KERNEL}"
"""


SYSCALLS = {"ps3": dict(SYSREG=11, SYS_WRITE=403, SYS_EXIT=22, TTY_FD=0),
            "linux": dict(SYSREG=0, SYS_WRITE=4, SYS_EXIT=1, TTY_FD=1)}


def build(kernel_path, n_bytes, scratch_size, scratch_alloc, workdir, clang="clang", objcopy="llvm-objcopy",
          flavour="ps3"):
    """flavour="linux" builds the same stub as a static Linux ELF (for checking it under qemu-ppc64)."""
    import os
    import subprocess
    opd_off, digits_off, param_off, pwlen_off = 0x0, 0x10, 0x20, 0x60
    out_off = 0x100
    scratch_off = (out_off + n_bytes + 0xFF) & ~0xFF
    line_off = (scratch_off + scratch_alloc + 0xFF) & ~0xFF
    data_mem = line_off + 16 + 2 * LINE_BYTES + 16
    total = n_bytes + scratch_size

    asm = STUB_S.format(OUT=DATA_BASE + out_off, SCRATCH=DATA_BASE + scratch_off, LINE=DATA_BASE + line_off,
                        DIGITS=DATA_BASE + digits_off, PWLEN=DATA_BASE + pwlen_off, N=n_bytes,
                        SCRATCH_SIZE=scratch_size, LINE_BYTES=LINE_BYTES, KERNEL=os.path.abspath(kernel_path),
                        **SYSCALLS[flavour])
    if flavour == "linux":
        asm += (f"    .data\n    .space {digits_off}\n    .ascii \"0123456789abcdef\"\n"
                f"    .space {data_mem - digits_off - 16}\n")
    src, obj, binf = (os.path.join(workdir, f) for f in ("ps3_stub.S", "ps3_stub.o", "ps3_code.bin"))
    with open(src, "w") as f:
        f.write(asm)
    subprocess.run([clang, "--target=powerpc64-unknown-linux-gnu", "-mcpu=pwr7", "-c", src, "-o", obj], check=True)
    relocs = subprocess.run(["llvm-readelf", "-r", obj], capture_output=True, text=True, check=True).stdout
    if "Relocation section" in relocs:
        raise SystemExit("ps3_stub.o has relocations")
    if flavour == "linux":
        exe = os.path.join(workdir, "ps3_stub_linux.elf")
        subprocess.run(["ld.lld", "-static", f"--section-start=.text={CODE_BASE:#x}",
                        f"--section-start=.data={DATA_BASE:#x}", obj, "-o", exe], check=True)
        return exe, total
    subprocess.run([objcopy, "-O", "binary", "--only-section=.text", obj, binf], check=True)
    code = open(binf, "rb").read()

    data = bytearray(0x100)
    struct.pack_into(">II", data, opd_off, CODE_BASE, 0)                  # OPD of _start: code, TOC
    data[digits_off:digits_off + 16] = b"0123456789abcdef"
    struct.pack_into(">IIIIiIII", data, param_off, 32, SYS_PROCESS_PARAM_MAGIC, 0x00009000, 0x00250001,
                     1001, 0x10000, 0x100000, 0)

    ehsize, phentsize, phnum = 64, 56, 3
    code_off = 0x1000
    data_off_file = (code_off + len(code) + 0xFFF) & ~0xFFF
    ph = [struct.pack(">IIQQQQQQ", 1, 0x400005, code_off, CODE_BASE, CODE_BASE, len(code), len(code), 0x10000),
          struct.pack(">IIQQQQQQ", 1, 0x600006, data_off_file, DATA_BASE, DATA_BASE, len(data), data_mem, 0x10000),
          struct.pack(">IIQQQQQQ", 0x60000001, 0, data_off_file + param_off, DATA_BASE + param_off,
                      DATA_BASE + param_off, 32, 32, 8)]
    ident = b"\x7fELF" + bytes([2, 2, 1, 0x66]) + bytes(8)                 # ELF64, BE, v1, OSABI CellOS LV-2
    eh = ident + struct.pack(">HHIQQQIHHHHHH", 2, 21, 1, DATA_BASE + opd_off, ehsize, 0, 0,
                             ehsize, phentsize, phnum, 64, 0, 0)
    img = bytearray(data_off_file + len(data))
    img[:len(eh)] = eh
    for i, p in enumerate(ph):
        img[ehsize + i * phentsize:ehsize + (i + 1) * phentsize] = p
    img[code_off:code_off + len(code)] = code
    img[data_off_file:data_off_file + len(data)] = data
    return bytes(img), total


def tty_to_bin(text, total):
    """Rebuild the result bytes from TTY output; raises if any range is missing."""
    out = bytearray(total)
    seen = bytearray(total)
    for line in text.splitlines():
        i = line.find("@@")
        if i < 0:
            continue
        head, _, hexpart = line[i + 2:].partition(" ")
        off = int(head, 16)
        chunk = bytes.fromhex(hexpart.strip())
        out[off:off + len(chunk)] = chunk
        seen[off:off + len(chunk)] = b"\1" * len(chunk)
    if not all(seen):
        missing = seen.index(0)
        raise ValueError(f"TTY output incomplete: first missing byte at offset {missing:#x} of {total:#x}")
    return bytes(out)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    import os
    meta = json.load(open(sys.argv[2]))
    img, total = build(sys.argv[1], meta["count"] * meta["record_size"], meta["scratch_size"], meta["scratch_alloc"],
                       os.path.dirname(os.path.abspath(sys.argv[3])))
    open(sys.argv[3], "wb").write(img)
    print(f"{sys.argv[3]}: {len(img)} bytes, prints {total} result bytes")
