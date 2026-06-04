#!/usr/bin/env bash
# Build Picard OSS .deb for Linux x86_64.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export ROOT
export TARGET="x86_64-unknown-linux-gnu"
export BUNDLES="deb"

# shellcheck source=lib/tauri-platform-build.sh
source "$ROOT/scripts/lib/tauri-platform-build.sh"

find target/x86_64-unknown-linux-gnu/release/bundle/deb -name '*.deb' 2>/dev/null | head -1
