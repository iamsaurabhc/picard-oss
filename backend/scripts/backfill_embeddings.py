#!/usr/bin/env python3
"""Build chunk embeddings for hybrid search on already-parsed documents.

After installing fastembed and setting ENABLE_HYBRID_SEARCH=true, run this once to
populate chunk_embeddings without re-parsing PDFs (FTS5 + chunks are unchanged).

Usage (from repo root):
  cd backend && source .venv/bin/activate
  pip install fastembed
  # EMBEDDING_MODEL_ID=BAAI/bge-small-en-v1.5  (recommended; not all-MiniLM-L6-v2)
  # ENABLE_HYBRID_SEARCH=true in backend/.env
  python scripts/download_embedding_model.py   # once — fixes missing model.onnx
  python scripts/backfill_embeddings.py

Optional full re-parse (slow — rebuilds chunks, FTS, entities, and embeddings):
  python scripts/backfill_embeddings.py --reparse
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

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


def _check_fastembed() -> None:
    try:
        import fastembed  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "fastembed is not installed. Run: pip install fastembed"
        ) from exc


def backfill_embeddings(db, document_id: str) -> int:
    from app.services.chunk_embeddings import index_document_after_parse

    return index_document_after_parse(db, document_id)


def reparse_document(document_id: str) -> str:
    from app.services.ingestion import enqueue_parse_document

    return enqueue_parse_document(document_id)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Index chunk embeddings for hybrid search (or optionally re-parse PDFs).",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / ".picard-data" / "picard.db",
        help="SQLite database path (default: .picard-data/picard.db)",
    )
    parser.add_argument(
        "--workspace-id",
        type=str,
        default=None,
        help="Only process documents in this workspace",
    )
    parser.add_argument(
        "--document-id",
        type=str,
        default=None,
        help="Only process a single document",
    )
    parser.add_argument(
        "--reparse",
        action="store_true",
        help="Re-enqueue full PDF parse (chunks + FTS + entities + embeddings)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List documents that would be processed, then exit",
    )
    args = parser.parse_args()
    _configure_db(args.db)

    from sqlalchemy import select

    from app.config import settings
    from app.db.models import Document
    from app.db.session import SessionLocal

    if not args.reparse:
        _check_fastembed()
        os.environ["ENABLE_HYBRID_SEARCH"] = "true"
        settings.enable_hybrid_search = True

    db = SessionLocal()
    try:
        stmt = select(Document).where(Document.parse_status == "done")
        if args.workspace_id:
            stmt = stmt.where(Document.workspace_id == args.workspace_id)
        if args.document_id:
            stmt = stmt.where(Document.id == args.document_id)
        docs = db.scalars(stmt).all()

        if not docs:
            print("No parsed documents found.")
            return 0

        if args.dry_run:
            for doc in docs:
                print(f"  {doc.id}  {doc.file_name}")
            print(f"Would process {len(docs)} document(s)")
            return 0

        if args.reparse:
            print(f"Re-parsing {len(docs)} document(s) (async jobs)...")
            for doc in docs:
                job_id = reparse_document(doc.id)
                print(f"  {doc.id} ({doc.file_name}) -> job {job_id}")
            print("Wait for parse jobs to finish in the UI or jobs table.")
            return 0

        from app.services.chunk_embeddings import preload_embedder

        print(
            f"Indexing embeddings ({settings.embedding_model_id}) "
            f"for {len(docs)} document(s)..."
        )
        try:
            preload_embedder()
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 1

        total_chunks = 0
        skipped = 0
        for doc in docs:
            count = backfill_embeddings(db, doc.id)
            if count == 0:
                skipped += 1
                print(f"  {doc.id} ({doc.file_name}): 0 chunks (no chunks or embed failed)")
            else:
                total_chunks += count
                print(f"  {doc.id} ({doc.file_name}): {count} chunks")
        print(f"Done: {total_chunks} chunk embeddings across {len(docs) - skipped} documents")
        if skipped:
            print(f"Skipped {skipped} document(s) with no indexed chunks")
        return 0 if total_chunks > 0 or not docs else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
