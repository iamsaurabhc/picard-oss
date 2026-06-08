#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/frontend/node_modules/@matbee/libreoffice-converter"
DEST="$ROOT/frontend/public/libreoffice-wasm"
DIST="$SRC/dist"

if [ ! -d "$SRC/wasm" ]; then
  echo "LibreOffice WASM not found — run npm install in frontend/ (needs @matbee/libreoffice-converter)" >&2
  exit 1
fi

mkdir -p "$DEST"
cp "$SRC/wasm/soffice.js" "$SRC/wasm/soffice.wasm" "$SRC/wasm/soffice.data" "$SRC/wasm/soffice.worker.js" "$DEST/"
cp "$DIST/browser.worker.global.js" "$DEST/"
echo "Copied LibreOffice WASM assets to frontend/public/libreoffice-wasm/"
