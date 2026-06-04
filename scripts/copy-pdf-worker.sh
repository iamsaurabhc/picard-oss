#!/usr/bin/env bash
# Copy pdf.js worker that matches react-pdf's pdfjs API (avoid 4.8 vs 4.10 mismatch).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND="$ROOT/frontend"
PUBLIC="$FRONTEND/public/pdf.worker.min.mjs"

# react-pdf pins pdfjs-dist; hoisted root copy may be a different major line.
WORKER="$FRONTEND/node_modules/react-pdf/node_modules/pdfjs-dist/build/pdf.worker.min.mjs"
if [ ! -f "$WORKER" ]; then
  WORKER="$FRONTEND/node_modules/pdfjs-dist/build/pdf.worker.min.mjs"
fi
if [ ! -f "$WORKER" ]; then
  echo "pdf.worker.min.mjs not found — run npm install in frontend/" >&2
  exit 1
fi

mkdir -p "$FRONTEND/public"
cp -f "$WORKER" "$PUBLIC"
API_VER="$(node -p "require('pdfjs-dist/package.json').version" 2>/dev/null || echo unknown)"
echo "Copied pdf.worker.min.mjs (pdfjs-dist $API_VER from $(dirname "$WORKER"))"
