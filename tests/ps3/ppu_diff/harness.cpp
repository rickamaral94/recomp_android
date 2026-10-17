// SPDX-License-Identifier: GPL-3.0-or-later
// Host side of the PPU differential test: the minimal runtime contract the ps3recomp lifter's
// output links against, plus a main() that runs the lifted kernel and dumps its results.
//
// Memory is big-endian guest memory at vm_base. Indirect calls are dispatched through the lifted
// function table. Anything the kernel is not supposed to reach (syscalls, HLE imports, the
// timebase, a call to an address that is not a function) aborts loudly: a stub that returned
// quietly would let a broken lift pass.
#include "ppu_recomp.h"

#include <sys/mman.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>

extern "C" {
uint8_t* vm_base = nullptr;
int vm_inline_ok = 1;
uint32_t ppu_vm_size = 0;
uint32_t ppu_hle_inject_base = 0;
PPU_THREAD_LOCAL void (*g_trampoline_fn)(void*) = nullptr;
}

namespace {

constexpr uint64_t kVmSize = 0x40000000ull; // 1 GiB of guest address space, lazily backed
constexpr uint32_t kScratch = 0x20000000u;
constexpr uint32_t kOut = 0x30000000u;
constexpr uint32_t kKernelBase = 0x10000u;  // where the kernel image (code + TOC + tables) is loaded

[[noreturn]] void fail(const char* what, uint64_t value) {
    std::fprintf(stderr, "ppu_diff harness: unexpected %s (0x%llx)\n", what, static_cast<unsigned long long>(value));
    std::abort();
}

uint8_t* at(uint64_t addr, uint32_t n) {
    if (addr + n > kVmSize) fail("guest access outside the test address space", addr);
    return vm_base + addr;
}

template <typename T> T load_be(uint64_t addr) {
    uint8_t* p = at(addr, sizeof(T));
    T v = 0;
    for (size_t i = 0; i < sizeof(T); ++i) v = static_cast<T>((v << 8) | p[i]);
    return v;
}

template <typename T> void store_be(uint64_t addr, T v) {
    uint8_t* p = at(addr, sizeof(T));
    for (size_t i = 0; i < sizeof(T); ++i) p[sizeof(T) - 1 - i] = static_cast<uint8_t>(v >> (8 * i));
}

bool write_all(const uint8_t* p, size_t n) {
    while (n) {
        const size_t w = std::fwrite(p, 1, n, stdout);
        if (w == 0) return false;
        p += w;
        n -= w;
    }
    return true;
}

} // namespace

extern "C" {
// The header maps vm_readN to inline fast paths; these are the out-of-line versions it falls
// back to. Parentheses keep the macros from expanding here.
uint8_t (vm_read8)(uint64_t a) { return load_be<uint8_t>(a); }
uint16_t (vm_read16)(uint64_t a) { return load_be<uint16_t>(a); }
uint32_t (vm_read32)(uint64_t a) { return load_be<uint32_t>(a); }
uint64_t (vm_read64)(uint64_t a) { return load_be<uint64_t>(a); }
void vm_write8(uint64_t a, uint8_t v) { store_be(a, v); }
void vm_write16(uint64_t a, uint16_t v) { store_be(a, v); }
void vm_write32(uint64_t a, uint32_t v) { store_be(a, v); }
void vm_write64(uint64_t a, uint64_t v) { store_be(a, v); }
int ppu_stwcx32(uint64_t a, uint32_t expected, uint32_t v) {
    if (load_be<uint32_t>(a) != expected) return 0;
    store_be(a, v);
    return 1;
}
int ppu_stdcx64(uint64_t a, uint64_t expected, uint64_t v) {
    if (load_be<uint64_t>(a) != expected) return 0;
    store_be(a, v);
    return 1;
}
void lv2_syscall(ppu_context* ctx) { fail("syscall", ctx->gpr[11]); }
uint64_t ppu_timebase_now(void) { fail("timebase read", 0); }
// bctr/bctrl/blrl: run the lifted function that starts at the guest address. An address that is
// not a function start is a lift failure, reported rather than guessed.
void ps3_indirect_call_to(ppu_context* ctx, uint32_t target) {
    for (uint64_t i = 0; i < function_table_count; ++i)
        if (function_table[i].addr == target) {
            function_table[i].func(ctx);
            return;
        }
    fail("indirect call to an address that is not a lifted function start", target);
}
void ps3_indirect_call(ppu_context* ctx) { ps3_indirect_call_to(ctx, static_cast<uint32_t>(ctx->ctr)); }
void ps3_hle_call(unsigned int nid, ppu_context*) { fail("HLE import call", nid); }
}

int main(int argc, char** argv) {
    if (argc != 3) {
        std::fprintf(stderr, "usage: %s RECORD_BYTES KERNEL_BIN > results.bin\n", argv[0]);
        return 2;
    }
    const unsigned long record_bytes = std::strtoul(argv[1], nullptr, 0);
    void* mem = mmap(nullptr, kVmSize, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
    if (mem == MAP_FAILED) {
        std::perror("mmap");
        return 1;
    }
    vm_base = static_cast<uint8_t*>(mem);

    // Load the kernel image, as a loader maps the ELF's segments: the code reads its own TOC,
    // jump tables and descriptors from guest memory.
    FILE* img = std::fopen(argv[2], "rb");
    if (!img) {
        std::perror(argv[2]);
        return 1;
    }
    const size_t img_len = std::fread(vm_base + kKernelBase, 1, kScratch - kKernelBase, img);
    std::fclose(img);
    if (img_len == 0) {
        std::fprintf(stderr, "ppu_diff harness: empty kernel image %s\n", argv[2]);
        return 1;
    }

    static ppu_context ctx; // zero-initialised, 16-byte aligned VR file
    ctx.gpr[3] = kOut;
    ctx.gpr[9] = kScratch;
    func_00010000(&ctx);

    if (ctx.gpr[3] != kOut + record_bytes) {
        std::fprintf(stderr, "ppu_diff harness: kernel wrote %llu bytes, expected %lu\n",
                     static_cast<unsigned long long>(ctx.gpr[3] - kOut), record_bytes);
        return 1;
    }
    // Same layout the oracle writes: all records, then the final scratch memory.
    if (!write_all(vm_base + kOut, record_bytes) || !write_all(vm_base + kScratch, 256)) return 1;
    return std::fflush(stdout) == 0 ? 0 : 1;
}
