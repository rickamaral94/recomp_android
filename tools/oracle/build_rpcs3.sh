#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Build the RPCS3 used as the second PPU oracle (tests/ps3/ppu_diff/run_rpcs3_oracle.py):
# upstream RPCS3 at the commit Armadasx3 last synced with, interpreter only (no LLVM), on
# Ubuntu 24.04 x86_64. RPCS3 is GPL-2.0-only and is used as a separate program, never linked
# into this project.
#
# Usage: tools/oracle/build_rpcs3.sh [WORK_DIR]   (default: ~/oracle; needs ~6 GB and sudo for apt)
# Result: WORK_DIR/rpcs3/build/bin/rpcs3
#
# Every workaround below was needed on Ubuntu 24.04 (2026-10-17):
#   - GCC 13: RPCS3 wants clang >= 19, the distro clang is 18;
#   - Qt 6.9.3 from download.qt.io via aqtinstall: RPCS3 wants Qt >= 6.7, the distro has 6.4.2;
#   - bundled FFmpeg: the distro's 6.1 lacks avcodec_get_supported_config (FFmpeg 7.1);
#   - USE_SDL=OFF (SDL's X11 deps) and USE_DISCORD_RPC=OFF: not needed for the oracle;
#   - extra link libraries: libxkbcommon after xkbcommon-x11, and libswresample/libavutil again
#     after libswscale (static link order).
set -euo pipefail

RPCS3_COMMIT=26098fb42d090cd522b4afcf3b754dd987c82978   # 2026-10-10, synced by Armadasx3
QT_VERSION=6.9.3
WORK=${1:-$HOME/oracle}
mkdir -p "$WORK"
cd "$WORK"

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential cmake ninja-build git python3-venv nasm \
    libgl-dev libglew-dev libegl-dev libevdev-dev libudev-dev libpulse-dev libasound2-dev \
    libcurl4-openssl-dev libjack-jackd2-dev libsndio-dev libwayland-dev libxrandr-dev libxi-dev \
    libx11-xcb-dev libxkbcommon-dev libxkbcommon-x11-dev libxcursor-dev libopenal-dev libzstd-dev \
    libvulkan-dev

if [ ! -x "$WORK/qt/$QT_VERSION/gcc_64/bin/qmake" ]; then
    python3 -m venv "$WORK/venv"
    "$WORK/venv/bin/pip" install -q aqtinstall
    "$WORK/venv/bin/aqt" install-qt linux desktop "$QT_VERSION" linux_gcc_64 -m qtmultimedia -O "$WORK/qt"
fi

if [ ! -d rpcs3/.git ]; then
    git init -q rpcs3
    git -C rpcs3 remote add origin https://github.com/RPCS3/rpcs3
fi
# GitHub serves a commit by full hash; a bounded history fetch finds it if that is refused.
git -C rpcs3 fetch -q --depth 1 origin "$RPCS3_COMMIT" || git -C rpcs3 fetch -q --depth 600 origin master
git -C rpcs3 checkout -q "$RPCS3_COMMIT"
subs=$(git -C rpcs3 config -f .gitmodules --get-regexp 'submodule\..*\.path' | awk '{print $2}' \
       | grep -vE 'llvm|opencv|discord-rpc')
git -C rpcs3 submodule update --init --depth 1 --jobs 4 $subs

FF=$WORK/rpcs3/build/3rdparty/ffmpeg/lib
cmake -S rpcs3 -B rpcs3/build -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++ \
    -DCMAKE_PREFIX_PATH="$WORK/qt/$QT_VERSION/gcc_64" \
    -DWITH_LLVM=OFF -DUSE_LTO=OFF -DUSE_NATIVE_INSTRUCTIONS=OFF -DUSE_PRECOMPILED_HEADERS=ON \
    -DUSE_SYSTEM_FFMPEG=OFF -DUSE_SDL=OFF -DUSE_DISCORD_RPC=OFF -DUSE_SYSTEM_OPENCV=OFF \
    -DCMAKE_CXX_STANDARD_LIBRARIES="-lxkbcommon $FF/libswresample.a $FF/libavutil.a"
ninja -C rpcs3/build -j"$(nproc)" rpcs3
echo "built: $WORK/rpcs3/build/bin/rpcs3"
