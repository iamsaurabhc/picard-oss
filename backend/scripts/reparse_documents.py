#!/usr/bin/env python3
"""Re-parse all documents to update chunk bounding boxes.

After fixing chunk_builder.py to use page-proportional fallback dimensions
instead of 1-point slivers, existing documents retain stale bboxes. This
script re-parses them so highlights render correctly.

Usage:
    # Re-parse all documents across all workspaces
    python -m scripts.reparse_documents

    # Re-parse documents in a specific workspace
    python -m scripts.reparse_documents --workspace-id <id>

    # Re-parse a single document
    python -m scripts.reparse_documents --document-id <id>

    # Dry-run (list documents that would be re-parsed)
    python -m scripts.reparse_documents --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from sqlalchemy import delete, select

# Ensure the backend app module is importable
sys.path.insert(0, ".")

from app.db.models import Chunk, Document
from app.db.session import SessionLocal, init_db
from app.services.chunk_builder import build_chunks_from_pdf, new_chunk_id
from app.services.docx_chunk_builder import build_chunks_from_docx
from app.services.parse_plan import build_parse_plan
from app.services.storage import resolve_document_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def reparse_document(db, doc: Document) -> int:
    """Re-parse a single document, returning the new chunk count."""
    file_path = resolve_document_path(doc.local_path)
    if not file_path.exists():
        logger.warning("  File not found: %s — skipping", file_path)
        return -1

    file_type = getattr(doc, "file_type", None) or "pdf"
    if file_type == "docx":
        chunks, page_count, parse_meta = build_chunks_from_docx(str(file_path))
    else:
        plan = build_parse_plan(str(file_path))
        chunks, page_count, parse_meta = build_chunks_from_pdf(str(file_path), plan=plan)

    # Delete old chunks
    db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    db.flush()

    # Insert new chunks with updated bboxes
    for built in chunks:
        db.add(
            Chunk(
                id=new_chunk_id(),
                document_id=doc.id,
                page_number=built.page_number,
                chunk_type=built.chunk_type,
                bbox_json=built.bbox_json,
                text_content=built.text_content,
                heading_path=built.heading_path,
                section_key=built.section_key,
                token_count=built.token_count,
                anchor_json=built.anchor_json,
            )
        )

    # Update document metadata
    doc.page_count = page_count
    doc.text_source = parse_meta.get("text_source")
    doc.ocr_engine = parse_meta.get("ocr_engine")
    doc.parse_status = "done"
    doc.parse_error = None
    db.commit()

    # Re-index entities if available
    try:
        from app.services.entity_index import extract_entities_for_document
        extract_entities_for_document(db, doc.id)
    except Exception as exc:
        logger.warning("  Entity extraction failed: %s", exc)

    # Re-index embeddings if enabled
    try:
        from app.config import settings
        if settings.enable_hybrid_search:
            from app.services.chunk_embeddings import (
                ensure_embedding_model,
                index_document_after_parse,
            )
            if ensure_embedding_model():
                index_document_after_parse(db, doc.id)
    except Exception as exc:
        logger.warning("  Embedding re-index failed: %s", exc)

    return len(chunks)


def main():
    parser = argparse.ArgumentParser(description="Re-parse documents to update chunk bboxes")
    parser.add_argument("--workspace-id", help="Only re-parse documents in this workspace")
    parser.add_argument("--document-id", help="Only re-parse this specific document")
    parser.add_argument("--dry-run", action="store_true", help="List documents without re-parsing")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()

    try:
        # Build query
        stmt = select(Document).where(Document.parse_status == "done")
        if args.document_id:
            stmt = stmt.where(Document.id == args.document_id)
        elif args.workspace_id:
            stmt = stmt.where(Document.workspace_id == args.workspace_id)

        docs = db.scalars(stmt).all()
        logger.info("Found %d document(s) to re-parse", len(docs))

        if args.dry_run:
            for doc in docs:
                logger.info(
                    "  [DRY-RUN] %s  workspace=%s  file=%s  pages=%s",
                    doc.id, doc.workspace_id, doc.file_name, doc.page_count,
                )
            return

        success = 0
        failed = 0
        total_chunks = 0
        start = time.time()

        for i, doc in enumerate(docs, 1):
            logger.info(
                "[%d/%d] Re-parsing %s (%s, %s pages)...",
                i, len(docs), doc.id, doc.file_name, doc.page_count,
            )
            try:
                count = reparse_document(db, doc)
                if count >= 0:
                    success += 1
                    total_chunks += count
                    logger.info("  ✓ %d chunks", count)
                else:
                    failed += 1
            except Exception as exc:
                failed += 1
                logger.error("  ✗ Failed: %s", exc)
                db.rollback()

        elapsed = time.time() - start
        logger.info(
            "Done. %d succeeded, %d failed, %d total chunks in %.1fs",
            success, failed, total_chunks, elapsed,
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
