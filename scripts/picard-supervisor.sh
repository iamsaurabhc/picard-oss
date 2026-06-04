#!/usr/bin/env bash
# Production supervisor: FastAPI + Next.js standalone (no --reload).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PICARD_DATA_DIR="${PICARD_DATA_DIR:-$ROOT/.picard-data}"
export DATABASE_URL="${DATABASE_URL:-sqlite:///$PICARD_DATA_DIR/picard.db}"
export PICARD_CHANNEL="${PICARD_CHANNEL:-stable}"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
HOST="${PICARD_HOST:-127.0.0.1}"

if [ ! -d backend/.venv ]; then
  python3 -m venv backend/.venv
fi
# shellcheck disable=SC1091
source backend/.venv/bin/activate
pip install -q -r backend/requirements-core.txt

if [ ! -d frontend/.next/standalone ]; then
  echo "Building frontend (standalone)..."
  (cd frontend && npm ci && npm run build)
fi

trap 'kill 0' EXIT

if [ "${START_PADDLE_OCR:-0}" = "1" ] && [ -x "$ROOT/scripts/start-paddleocr.sh" ]; then
  "$ROOT/scripts/start-paddleocr.sh" &
fi

(
  cd backend
  if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
  fi
  export PICARD_DATA_DIR
  export DATABASE_URL
  uvicorn app.main:app --host "$HOST" --port "$BACKEND_PORT"
) &

(
  cd frontend
  export PORT="$FRONTEND_PORT"
  export HOSTNAME="$HOST"
  node .next/standalone/server.js
) &

echo "Picard OSS: http://${HOST}:${FRONTEND_PORT} (API :${BACKEND_PORT})"
wait
