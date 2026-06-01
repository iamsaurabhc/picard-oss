#!/usr/bin/env python3
"""Benchmark simple search latency on Chester corpus."""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.services.fts_search import fts_search
from tests.conftest import resolve_corpus_db_path
from tests.corpus_constants import WORKSPACE_ID


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
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Session = sessionmaker(bind=engine)
    db = Session()
    queries = ["liability", "negligence", "Hambrook"]
    times: list[float] = []
    for _ in range(20):
        for q in queries:
            t0 = time.perf_counter()
            fts_search(db, query=q, workspace_id=WORKSPACE_ID, top_k=12)
            times.append((time.perf_counter() - t0) * 1000)
    db.close()
    print(f"p50_ms={statistics.median(times):.2f}")
    print(f"p95_ms={sorted(times)[int(len(times) * 0.95)]:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
