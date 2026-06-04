#!/usr/bin/env bash
# Build Picard OSS NSIS installer for Windows x64.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export ROOT
export TARGET="x86_64-pc-windows-msvc"
export BUNDLES="nsis"

# shellcheck source=lib/tauri-platform-build.sh
source "$ROOT/scripts/lib/tauri-platform-build.sh"

find target/x86_64-pc-windows-msvc/release/bundle/nsis -name '*.exe' 2>/dev/null | head -1
