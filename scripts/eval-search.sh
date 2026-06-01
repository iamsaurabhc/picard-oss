#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
python -m pytest -m "not slow and not corpus" -q
python -m pytest -m corpus -q
python scripts/eval_scorecard.py || true
python scripts/eval_entity_ab.py --skip-hybrid || true
python scripts/benchmark_search.py
