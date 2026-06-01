#!/usr/bin/env python3
"""A/B benchmark: rules-only vs hybrid (GLiNER) entity extraction on golden queries."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

BENCHMARK_PATH = BACKEND / "eval" / "gold_entity_benchmark.jsonl"
REPORT_PATH = ROOT / "docs" / "phase3-entity-ab.md"

_env = BACKEND / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

# Model is saved under backend/.picard-data when scripts run from backend/
_backend_data = BACKEND / ".picard-data"
if (_backend_data / "models").exists():
    os.environ.setdefault("PICARD_DATA_DIR", str(_backend_data))
else:
    os.environ.setdefault("PICARD_DATA_DIR", str(ROOT / ".picard-data"))


def _configure_db(db_path: Path) -> None:
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.resolve()}"


def _sync_settings() -> None:
    from pathlib import Path

    from app.config import settings

    if data := os.environ.get("PICARD_DATA_DIR"):
        settings.picard_data_dir = Path(data)
    if url := os.environ.get("DATABASE_URL"):
        settings.database_url = url


def _backfill_all(db_path: Path, *, enable_ner: bool) -> None:
    _configure_db(db_path)
    _sync_settings()
    from app.config import settings
    from app.services.entity_extraction.ner.gliner_engine import _load_model

    _load_model.cache_clear()
    os.environ["ENABLE_NER_ENTITY_EXTRACT"] = "true" if enable_ner else "false"
    settings.enable_ner_entity_extract = enable_ner
    settings.database_url = f"sqlite:///{db_path.resolve()}"
    print(f"  backfill enable_ner={enable_ner} model_dir_exists={(settings.picard_data_dir / 'models' / settings.ner_model_name).exists()}")

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.db.models import Document
    from scripts.backfill_entities import backfill_document

    engine = create_engine(
        f"sqlite:///{db_path.resolve()}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = Session()
    try:
        docs = db.scalars(select(Document.id).where(Document.parse_status == "done")).all()
        for doc_id in docs:
            backfill_document(db, doc_id)
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Source DB (default: test corpus snapshot)",
    )
    parser.add_argument("--skip-hybrid", action="store_true", help="Only run rules baseline")
    parser.add_argument("--in-place", action="store_true", help="Mutate --db instead of temp copy")
    args = parser.parse_args()

    source = args.db
    if source is None:
        source = BACKEND / "test" / "fixtures" / "corpus" / "picard-corpus.db"
        if not source.exists():
            source = ROOT / ".picard-data" / "picard.db"
    if not source.exists():
        print(f"No database at {source}", file=sys.stderr)
        return 1

    from sqlalchemy import create_engine

    from app.db.bootstrap import run_migrations

    if args.in_place:
        rules_db = hybrid_db = source
    else:
        work = ROOT / ".picard-data" / "eval-ab"
        work.mkdir(parents=True, exist_ok=True)
        rules_db = work / "rules.db"
        hybrid_db = work / "hybrid.db"
        shutil.copy2(source, rules_db)
        shutil.copy2(source, hybrid_db)

    for db_path in {rules_db, hybrid_db}:
        eng = create_engine(f"sqlite:///{db_path.resolve()}")
        run_migrations(eng)
        eng.dispose()

    print("Backfill rules-only...")
    _backfill_all(rules_db, enable_ner=False)

    from sqlalchemy.orm import sessionmaker

    from app.config import settings
    from app.services.entity_extraction.ner.gliner_engine import ner_available
    from eval.entity_benchmark import compare_ab, format_markdown_report, run_benchmark

    _sync_settings()
    settings.enable_llm_query_understanding = False

    def _open_db(path: Path):
        eng = create_engine(
            f"sqlite:///{path.resolve()}",
            connect_args={"check_same_thread": False},
        )
        return sessionmaker(bind=eng, autocommit=False, autoflush=False)()

    db = _open_db(rules_db)
    try:
        rules_result = run_benchmark(db, BENCHMARK_PATH)
    finally:
        db.close()

    hybrid_result = rules_result
    hybrid_ok = False
    if not args.skip_hybrid and ner_available(require_enable_flag=False):
        print("Backfill hybrid (GLiNER)...")
        _backfill_all(hybrid_db, enable_ner=True)
        db = _open_db(hybrid_db)
        try:
            hybrid_result = run_benchmark(db, BENCHMARK_PATH)
            hybrid_ok = True
        finally:
            db.close()
    elif not args.skip_hybrid:
        print("GLiNER not available (install gliner + model); hybrid skipped.")

    comparison = compare_ab(rules_result, hybrid_result)
    report = {
        "comparison": comparison,
        "rules_per_query": rules_result["per_query"],
        "hybrid_per_query": hybrid_result["per_query"],
        "hybrid_ran": hybrid_ok,
    }
    print(json.dumps(report["comparison"], indent=2))

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(format_markdown_report(comparison, hybrid_available=hybrid_ok), encoding="utf-8")
    print(f"Wrote {REPORT_PATH}")
    return 0 if comparison["entity_ab_pass"] or not hybrid_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
