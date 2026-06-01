#!/usr/bin/env python3
"""Re-run entity extraction for all parsed documents (e.g. after new entity types)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import os

ROOT = Path(__file__).resolve().parents[2]
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

_env = BACKEND / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


def _configure_db(db_path: Path) -> None:
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.resolve()}"


def backfill_document(db, document_id: str) -> int:
    from sqlalchemy import delete

    from app.db.models import EntityMention, PageEntity
    from app.services.entity_index import extract_entities_for_document

    db.execute(delete(EntityMention).where(EntityMention.document_id == document_id))
    db.execute(delete(PageEntity).where(PageEntity.document_id == document_id))
    db.commit()
    return extract_entities_for_document(db, document_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / ".picard-data" / "picard.db",
        help="SQLite database path (default: repo .picard-data/picard.db)",
    )
    args = parser.parse_args()
    _configure_db(args.db)

    from sqlalchemy import select

    from app.db.models import Document
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        docs = db.scalars(select(Document.id).where(Document.parse_status == "done")).all()
        total = 0
        for doc_id in docs:
            count = backfill_document(db, doc_id)
            total += count
            print(f"  {doc_id}: {count} mentions")
        print(f"Backfilled {len(docs)} documents, {total} mentions")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
