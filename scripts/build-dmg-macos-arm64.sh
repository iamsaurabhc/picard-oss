#!/usr/bin/env bash
# Build Picard OSS .dmg for macOS Apple Silicon (aarch64).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export ROOT
export PATH="${HOME}/.cargo/bin:${PATH}"
export TARGET="aarch64-apple-darwin"
export BUNDLES="dmg"

ARCH="$(uname -m)"
if [ "$ARCH" != "arm64" ]; then
  echo "Warning: expected arm64 Mac (M1/M2/M3), got $ARCH."
fi

# shellcheck source=lib/tauri-platform-build.sh
source "$ROOT/scripts/lib/tauri-platform-build.sh"

DMG="$(find target/aarch64-apple-darwin/release/bundle/dmg -maxdepth 1 -name '*.dmg' -print -quit 2>/dev/null)"
if [ -z "$DMG" ]; then
  RW="$(find target/aarch64-apple-darwin/release/bundle -name 'rw.*.dmg' 2>/dev/null | head -1)"
  if [ -n "$RW" ]; then
    mkdir -p target/aarch64-apple-darwin/release/bundle/dmg
    OUT="target/aarch64-apple-darwin/release/bundle/dmg/Picard.Law OSS_$(cat "$ROOT/VERSION")_aarch64.dmg"
    hdiutil convert "$RW" -format UDZO -imagekey zlib-level=9 -o "$OUT"
    DMG="$OUT"
  fi
fi
if [ -n "$DMG" ]; then
  echo ""
  echo "Built: $(pwd)/$DMG"
  echo "Install: open \"$DMG\" and drag Picard.Law OSS to Applications."
else
  echo "DMG not found — .app may still be at target/.../bundle/macos/*.app"
  find target -name '*.dmg' 2>/dev/null || true
  exit 1
fi
