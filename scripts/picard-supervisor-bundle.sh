#!/usr/bin/env bash
# Runs inside Picard.app Resources — starts bundled backend + Next standalone.
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "$0")" && pwd)"
export PICARD_DATA_DIR="${PICARD_DATA_DIR:-$HOME/Library/Application Support/Picard}"
export DATABASE_URL="sqlite:///$PICARD_DATA_DIR/picard.db"
mkdir -p "$PICARD_DATA_DIR"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-13130}"

# Backend
if [ -d "$BUNDLE_ROOT/backend/.venv" ]; then
  # shellcheck disable=SC1091
  source "$BUNDLE_ROOT/backend/.venv/bin/activate"
fi
(
  cd "$BUNDLE_ROOT/backend"
  export PICARD_DATA_DIR DATABASE_URL
  if [ -f .venv/bin/python ]; then
    exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT"
  else
    exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT"
  fi
) &

# Frontend (Next standalone)
(
  cd "$BUNDLE_ROOT/frontend"
  export PORT="$FRONTEND_PORT"
  export HOSTNAME=127.0.0.1
  export NODE_ENV=production
  exec node server.js
) &

wait
