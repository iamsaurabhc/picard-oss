#!/usr/bin/env bash
# Index chunk embeddings for hybrid search (parsed PDFs only).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
if [[ -f .venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi
pip install -q fastembed
python scripts/download_embedding_model.py
python scripts/backfill_embeddings.py "$@"
