#!/usr/bin/env python3
"""Run Tier A eval scorecard against corpus DB."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from eval.runner import build_scorecard
from tests.conftest import resolve_corpus_db_path


def main() -> int:
    path = resolve_corpus_db_path()
    if not path:
        print("No corpus DB found", file=sys.stderr)
        return 1
    from app.db.bootstrap import run_migrations

    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_migrations(engine)

    @event.listens_for(engine, "connect")
    def pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Session = sessionmaker(bind=engine)
    db = Session()
    gold = Path(__file__).resolve().parents[1] / "eval" / "gold_labels.jsonl"
    scorecard = build_scorecard(db, gold)
    print(json.dumps(scorecard, indent=2))
    db.close()
    return 0 if scorecard.get("tier_a_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
