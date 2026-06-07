#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f backend/.env ] && [ -f .env.example ]; then
  cp .env.example backend/.env
fi
if [ ! -f frontend/.env.local ] && [ -f .env.example ]; then
  grep NEXT_PUBLIC .env.example > frontend/.env.local 2>/dev/null || true
fi

if [ ! -d backend/.venv ]; then
  python3 -m venv backend/.venv
fi
# shellcheck disable=SC1091
source backend/.venv/bin/activate
pip install -q -r backend/requirements.txt

_hybrid=0
if [ -f backend/.env ] && grep -qE '^[[:space:]]*ENABLE_HYBRID_SEARCH[[:space:]]*=[[:space:]]*true' backend/.env; then
  _hybrid=1
fi
if [ "$_hybrid" = "1" ]; then
  echo "Hybrid search enabled — ensuring embedding model (fastembed)..."
  (
    cd backend
    export PICARD_DATA_DIR="$ROOT/.picard-data"
    python scripts/download_embedding_model.py
  ) || echo "Warning: embedding model download failed; hybrid search may be degraded until fixed."
fi

if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm install)
fi

trap 'kill 0' EXIT

# Desktop .app binds 127.0.0.1:8000 (picard-backend). Dev uvicorn uses 0.0.0.0:8000 but
# browsers still reach the desktop API first — Settings/agent mode then look "stuck".
if pgrep -f picard-backend >/dev/null 2>&1; then
  echo "Stopping Picard desktop backend (picard-backend) so dev API can use port 8000…"
  echo "  Tip: quit Picard.Law OSS.app while running ./scripts/start.sh"
  pkill -f picard-backend 2>/dev/null || true
  sleep 1
fi

if [ "${START_PADDLE_OCR:-0}" = "1" ]; then
  if [ -x "$ROOT/scripts/start-paddleocr.sh" ]; then
    "$ROOT/scripts/start-paddleocr.sh" &
  fi
else
  echo "Tip: run START_PADDLE_OCR=1 ./scripts/start.sh (or ./scripts/start-paddleocr.sh) for PaddleOCR on scanned PDFs."
fi

(
  cd backend
  if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
  fi
  # Always use repo-root data dir (backend/.env uses relative paths for cwd=backend)
  export PICARD_DATA_DIR="$ROOT/.picard-data"
  export DATABASE_URL="sqlite:///$ROOT/.picard-data/picard.db"
  if lsof -iTCP:8000 -sTCP:LISTEN 2>/dev/null | grep -q picard-backend; then
    echo "ERROR: picard-backend still owns port 8000. Quit Picard.Law OSS.app, then re-run ./scripts/start.sh" >&2
    exit 1
  fi
  uvicorn app.main:app --reload --reload-exclude '.venv/*' --host 127.0.0.1 --port 8000
) &

(
  cd frontend
  npm run dev
) &

wait
