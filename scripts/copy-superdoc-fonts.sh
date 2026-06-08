#!/usr/bin/env bash
# Copy SuperDoc metric-compatible fonts to Next.js public/ (served at /fonts/).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND="$ROOT/frontend"
DEST="$FRONTEND/public/fonts"

SRC="$FRONTEND/node_modules/@superdoc-dev/react/node_modules/superdoc/dist/fonts"
if [ ! -d "$SRC" ]; then
  SRC="$FRONTEND/node_modules/superdoc/dist/fonts"
fi
if [ ! -d "$SRC" ]; then
  echo "SuperDoc fonts not found — run npm install in frontend/" >&2
  exit 1
fi

mkdir -p "$DEST"
cp -f "$SRC"/*.woff2 "$DEST/" 2>/dev/null || true
COUNT="$(find "$DEST" -maxdepth 1 -name '*.woff2' | wc -l | tr -d ' ')"
echo "Copied $COUNT SuperDoc font(s) to public/fonts/"
