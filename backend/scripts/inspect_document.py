#!/usr/bin/env python3
"""Audit parsed document structure against the source PDF."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text

from app.config import settings
from app.services.storage import resolve_pdf_path


def _pdf_page_count(pdf_path: Path) -> int | None:
    try:
        from liteparse import LiteParse

        return LiteParse().parse(str(pdf_path)).num_pages
    except Exception:
        pass
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(pdf_path)).pages)
    except Exception:
        return None


def inspect(document_id: str) -> int:
    db_path = settings.db_path
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.connect() as conn:
        doc = conn.execute(
            text(
                "SELECT id, file_name, local_path, page_count, parse_status, parse_error "
                "FROM documents WHERE id = :id"
            ),
            {"id": document_id},
        ).mappings().first()
        if not doc:
            print(f"Document not found: {document_id}", file=sys.stderr)
            return 1

        stats = conn.execute(
            text(
                """
                SELECT
                    COUNT(*) AS chunk_count,
                    MIN(page_number) AS min_page,
                    MAX(page_number) AS max_page,
                    COUNT(DISTINCT page_number) AS distinct_pages
                FROM chunks
                WHERE document_id = :id
                """
            ),
            {"id": document_id},
        ).mappings().one()

        gaps = conn.execute(
            text(
                """
                WITH RECURSIVE seq(n) AS (
                    SELECT :min_page
                    UNION ALL
                    SELECT n + 1 FROM seq WHERE n < :max_page
                )
                SELECT seq.n AS missing_page
                FROM seq
                LEFT JOIN (
                    SELECT DISTINCT page_number FROM chunks WHERE document_id = :id
                ) c ON c.page_number = seq.n
                WHERE c.page_number IS NULL
                ORDER BY seq.n
                LIMIT 20
                """
            ),
            {"id": document_id, "min_page": stats["min_page"] or 0, "max_page": stats["max_page"] or 0},
        ).scalars().all()

    pdf_path = resolve_pdf_path(doc["local_path"])
    actual_pages = _pdf_page_count(pdf_path)

    print(json.dumps({"document": dict(doc), "chunks": dict(stats), "pdf_path": str(pdf_path)}, indent=2))
    print()
    print(f"PDF pages (pypdf):     {actual_pages}")
    print(f"Stored page_count:     {doc['page_count']}")
    print(f"Chunk page range:      {stats['min_page']}–{stats['max_page']}")
    print(f"Distinct chunk pages:  {stats['distinct_pages']}")
    print(f"Total chunks:          {stats['chunk_count']}")

    ok = True
    if actual_pages is not None and doc["page_count"] != actual_pages:
        print(f"⚠ page_count mismatch: stored {doc['page_count']}, PDF has {actual_pages}")
        ok = False
    if stats["max_page"] and actual_pages and stats["max_page"] > actual_pages:
        print(f"⚠ chunk max page_number ({stats['max_page']}) exceeds PDF pages ({actual_pages})")
        ok = False
    if stats["distinct_pages"] and actual_pages and stats["distinct_pages"] != actual_pages:
        print(f"⚠ distinct chunk pages ({stats['distinct_pages']}) != PDF pages ({actual_pages})")
        ok = False
    if gaps:
        print(f"⚠ missing page numbers in chunks (first 20): {gaps}")
        ok = False

    if ok:
        print("✓ Extraction page structure looks consistent.")
    return 0 if ok else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit a parsed document's page structure")
    parser.add_argument("document_id", help="Document UUID from the documents table")
    args = parser.parse_args()
    raise SystemExit(inspect(args.document_id))
