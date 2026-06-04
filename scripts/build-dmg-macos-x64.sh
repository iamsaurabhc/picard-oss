#!/usr/bin/env bash
# Build Picard OSS .dmg for macOS Intel (x86_64).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export ROOT
export TARGET="x86_64-apple-darwin"
export BUNDLES="dmg"

# shellcheck source=lib/tauri-platform-build.sh
source "$ROOT/scripts/lib/tauri-platform-build.sh"

find target/x86_64-apple-darwin/release/bundle/dmg -name '*.dmg' 2>/dev/null | head -1
