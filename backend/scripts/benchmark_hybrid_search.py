#!/usr/bin/env python3
"""Benchmark hybrid chunk vs page vector search latency."""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.services.hybrid_search import vector_search
from app.services.page_embeddings import vector_page_search
from app.services.sqlite_vec import vec_backend_name
from tests.conftest import resolve_corpus_db_path
from tests.corpus_constants import DOCUMENT_ID, WORKSPACE_ID


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(round((pct / 100.0) * (len(ordered) - 1)))
    return ordered[max(0, min(idx, len(ordered) - 1))]


def main() -> int:
    path = resolve_corpus_db_path()
    if not path:
        print("No corpus DB", file=sys.stderr)
        return 1
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def pragma(dbapi_connection, connection_record):
        from app.services.sqlite_vec import try_load_sqlite_vec

        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
        try_load_sqlite_vec(dbapi_connection)

    Session = sessionmaker(bind=engine)
    db = Session()
    settings.enable_hybrid_search = True
    query = "negligence damages"
    chunk_times: list[float] = []
    page_times: list[float] = []
    overview_times: list[float] = []
    for _ in range(5):
        t0 = time.perf_counter()
        vector_search(db, query=query, workspace_id=WORKSPACE_ID, document_ids=None, top_k=16)
        chunk_times.append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        vector_page_search(
            db,
            queries=[query],
            workspace_id=WORKSPACE_ID,
            document_ids=[DOCUMENT_ID],
            top_k_per_query=8,
        )
        page_times.append((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        vector_page_search(
            db,
            queries=[query, "plaintiff damages", "liability cap"],
            workspace_id=WORKSPACE_ID,
            document_ids=[DOCUMENT_ID],
            top_k_per_query=6,
            fts_page_scores={1: 0.2},
        )
        overview_times.append((time.perf_counter() - t0) * 1000)
    db.close()
    ann = vec_backend_name()
    print(f"vector_backend={ann}")
    print(f"chunk_vector_p50_ms={statistics.median(chunk_times):.2f}")
    print(f"chunk_vector_p95_ms={_percentile(chunk_times, 95):.2f}")
    print(f"page_vector_p50_ms={statistics.median(page_times):.2f}")
    print(f"page_vector_p95_ms={_percentile(page_times, 95):.2f}")
    print(f"overview_facet_p50_ms={statistics.median(overview_times):.2f}")
    print(f"overview_facet_p95_ms={_percentile(overview_times, 95):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
