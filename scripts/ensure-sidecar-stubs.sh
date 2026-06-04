#!/usr/bin/env bash
# Create no-op sidecar stubs so `cargo check` / `tauri dev` succeed before PyInstaller build.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/desktop/src-tauri/bin"
mkdir -p "$BIN"

TARGET="${1:-$(rustc -vV | sed -n 's/^host: //p')}"

for name in picard-supervisor; do
  dest="$BIN/${name}-${TARGET}"
  if [ ! -f "$dest" ]; then
    printf '#!/bin/sh\nexit 0\n' >"$dest"
    chmod +x "$dest"
    echo "Stub: $dest"
  fi
done

RES="$ROOT/desktop/src-tauri/resources"
if [ ! -f "$RES/frontend/server.js" ]; then
  mkdir -p "$RES/frontend/.next/static" "$RES/node"
  echo "// stub" >"$RES/frontend/server.js"
  touch "$RES/frontend/.next/static/stub"
  printf '#!/bin/sh\nexit 0\n' >"$RES/node/node"
  chmod +x "$RES/node/node"
  echo "Stub: $RES/frontend/server.js"
fi
