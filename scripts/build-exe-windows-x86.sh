#!/usr/bin/env bash
# Build Picard OSS NSIS installer for Windows 32-bit.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export ROOT
export TARGET="i686-pc-windows-msvc"
export BUNDLES="nsis"

# shellcheck source=lib/tauri-platform-build.sh
source "$ROOT/scripts/lib/tauri-platform-build.sh"

find target/i686-pc-windows-msvc/release/bundle/nsis -name '*.exe' 2>/dev/null | head -1
