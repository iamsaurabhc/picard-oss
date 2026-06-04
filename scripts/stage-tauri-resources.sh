#!/usr/bin/env bash
# Stage Next standalone + bundled node for Tauri resources (no Python venv).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RES="$ROOT/desktop/src-tauri/resources"

if [ ! -f "$ROOT/frontend/.next/standalone/server.js" ]; then
  echo "Run frontend production build first (npm run build in frontend/)." >&2
  exit 1
fi

echo "==> Stage frontend standalone"
rm -rf "$RES/frontend" "$RES/node"
mkdir -p "$RES/frontend" "$RES/node"

# Standalone server + server chunks (no client static yet)
rsync -a "$ROOT/frontend/.next/standalone/" "$RES/frontend/"

# Client static must land at frontend/.next/static/{css,chunks,...} — NOT static/static/
rm -rf "$RES/frontend/.next/static"
mkdir -p "$RES/frontend/.next"
rsync -a "$ROOT/frontend/.next/static/" "$RES/frontend/.next/static/"

if [ -d "$ROOT/frontend/public" ]; then
  rsync -a "$ROOT/frontend/public/" "$RES/frontend/public/"
fi

if [ -d "$RES/frontend/.next/static/static" ]; then
  echo "ERROR: nested .next/static/static — client assets mis-staged" >&2
  exit 1
fi
if ! find "$RES/frontend/.next/static/css" -name '*.css' -print -quit 2>/dev/null | grep -q .; then
  echo "ERROR: no CSS under staged .next/static/css" >&2
  exit 1
fi

NODE_BIN="$(command -v node)"
cp "$NODE_BIN" "$RES/node/node"
chmod +x "$RES/node/node"
echo "Bundled node from $NODE_BIN"
echo "Staged static CSS: $(find "$RES/frontend/.next/static/css" -name '*.css' | wc -l | tr -d ' ') files"
