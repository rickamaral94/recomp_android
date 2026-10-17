// SPDX-License-Identifier: GPL-3.0-or-later
// Host side of the PPU differential test: the minimal runtime contract the ps3recomp lifter's
// output links against, plus a main() that runs the lifted kernel and dumps its results.
//
// Memory is big-endian guest memory at vm_base. Anything the kernel is not supposed to reach
// (syscalls, indirect calls, HLE imports, the timebase) aborts loudly: a stub that returned
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
void ps3_indirect_call(ppu_context* ctx) { fail("indirect call", ctx->ctr); }
void ps3_indirect_call_to(ppu_context*, uint32_t target) { fail("indirect call", target); }
void ps3_hle_call(unsigned int nid, ppu_context*) { fail("HLE import call", nid); }
}

int main(int argc, char** argv) {
    if (argc != 2) {
        std::fprintf(stderr, "usage: %s RECORD_BYTES > results.bin\n", argv[0]);
        return 2;
    }
    const unsigned long record_bytes = std::strtoul(argv[1], nullptr, 0);
    void* mem = mmap(nullptr, kVmSize, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
    if (mem == MAP_FAILED) {
        std::perror("mmap");
        return 1;
    }
    vm_base = static_cast<uint8_t*>(mem);

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
