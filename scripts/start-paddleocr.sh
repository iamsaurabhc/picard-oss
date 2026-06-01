#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OCR_DIR="$ROOT/backend/ocr/paddleocr"
PORT="${PADDLE_OCR_PORT:-8829}"

if [ ! -d "$ROOT/backend/.venv" ]; then
  echo "Create backend venv first: python3 -m venv backend/.venv && source backend/.venv/bin/activate && pip install -r backend/requirements.txt"
  exit 1
fi

# shellcheck disable=SC1091
source "$ROOT/backend/.venv/bin/activate"

if ! python -c "import paddleocr" 2>/dev/null; then
  echo "Installing PaddleOCR server dependencies (one-time, may take a few minutes)..."
  pip install -q -r "$OCR_DIR/requirements.txt"
fi

echo "PaddleOCR LiteParse API: http://127.0.0.1:${PORT}/ocr"
echo "Health: http://127.0.0.1:${PORT}/health"
cd "$OCR_DIR"
exec python server.py
