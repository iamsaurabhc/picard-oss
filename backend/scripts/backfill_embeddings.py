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
    resolved = db_path.resolve()
    os.environ["DATABASE_URL"] = f"sqlite:///{resolved}"
    os.environ["PICARD_DATA_DIR"] = str(resolved.parent)


def _open_session(db_path: Path):
    """Dedicated engine/session for the target DB (avoids stale global session)."""
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker

    from app.db.bootstrap import run_migrations

    url = f"sqlite:///{db_path.resolve()}"
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    run_migrations(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


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
        default=None,
        help="SQLite database path (default: PICARD_DATA_DIR/picard.db from settings)",
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
        "--vec-index",
        action="store_true",
        help="Rebuild page_embeddings from chunk_embeddings (no re-embed)",
    )
    parser.add_argument(
        "--vec-ann",
        action="store_true",
        help="Populate sqlite-vec chunk_vectors + page_vectors ANN from existing BLOBs",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List documents that would be processed, then exit",
    )
    args = parser.parse_args()

    from sqlalchemy import select

    from app.config import reload_settings, settings
    from app.db.models import Document

    reload_settings()
    db_path = args.db or settings.db_path
    _configure_db(db_path)
    reload_settings()

    if not args.reparse:
        _check_fastembed()
        os.environ["ENABLE_HYBRID_SEARCH"] = "true"
        settings.enable_hybrid_search = True

    db = _open_session(db_path)
    try:
        stmt = select(Document).where(Document.parse_status == "done")
        if args.workspace_id:
            stmt = stmt.where(Document.workspace_id == args.workspace_id)
        if args.document_id:
            stmt = stmt.where(Document.id == args.document_id)
        docs = db.scalars(stmt).all()

        if not docs:
            print(f"No parsed documents found in {db_path.resolve()}.")
            print(
                "If your corpus lives elsewhere, pass --db "
                "(e.g. ../.picard-data/picard.db when using ./scripts/start.sh)."
            )
            return 0

        if args.dry_run:
            for doc in docs:
                print(f"  {doc.id}  {doc.file_name}")
            print(f"Would process {len(docs)} document(s)")
            return 0

        if args.vec_index:
            from app.services.page_embeddings import backfill_page_embeddings_from_chunks

            total_pages = 0
            for doc in docs:
                n = backfill_page_embeddings_from_chunks(db, doc.id)
                db.commit()
                total_pages += n
                print(f"  {doc.id}: {n} page vectors")
            print(f"Done: {total_pages} page embeddings")
            return 0

        if args.vec_ann:
            from app.services.sqlite_vec import (
                backfill_chunk_vectors_from_blobs,
                backfill_page_vectors_from_blobs,
                vec_backend_name,
            )

            backend = vec_backend_name()
            if backend == "blob-scan":
                print(
                    "sqlite-vec ANN unavailable. Install: pip install apsw sqlite-vec",
                    file=sys.stderr,
                )
                return 1
            print(f"Using vector backend: {backend}")
            chunk_total = 0
            page_total = 0
            for doc in docs:
                c = backfill_chunk_vectors_from_blobs(db, doc.id)
                p = backfill_page_vectors_from_blobs(db, doc.id)
                db.commit()
                chunk_total += c
                page_total += p
                print(f"  {doc.id}: chunk_ann={c} page_ann={p}")
            print(f"Done: chunk_vectors={chunk_total}, page_vectors={page_total}")
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
        print(f"Done: {total_chunks} chunk embeddings (+ page vectors) across {len(docs) - skipped} documents")
        if skipped:
            print(f"Skipped {skipped} document(s) with no indexed chunks")
        return 0 if total_chunks > 0 or not docs else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
