#!/usr/bin/env bash
# Build Picard OSS .deb for Linux i386.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export ROOT
export TARGET="i686-unknown-linux-gnu"
export BUNDLES="deb"

# shellcheck source=lib/tauri-platform-build.sh
source "$ROOT/scripts/lib/tauri-platform-build.sh"

find target/i686-unknown-linux-gnu/release/bundle/deb -name '*.deb' 2>/dev/null | head -1
