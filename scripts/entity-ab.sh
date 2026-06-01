#!/usr/bin/env bash
# Rules vs GLiNER entity extraction A/B — always uses backend/.venv
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

pip install -q -r requirements.txt

export DATABASE_URL="${DATABASE_URL:-sqlite:///$ROOT/.picard-data/picard.db}"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
# Relative PICARD_DATA_DIR in .env resolves from backend/ (where model is cached)
export PICARD_DATA_DIR="${PICARD_DATA_DIR:-$ROOT/backend/.picard-data}"

echo "==> Download GLiNER model (if needed)"
python scripts/download_gliner_model.py

echo "==> Backfill live DB with hybrid NER"
export ENABLE_NER_ENTITY_EXTRACT=true
python scripts/backfill_entities.py

echo "==> Refresh corpus snapshot"
python scripts/export_test_corpus.py

echo "==> A/B benchmark (rules vs hybrid on 18 queries)"
python scripts/eval_entity_ab.py

echo "Report: $ROOT/docs/phase3-entity-ab.md"
