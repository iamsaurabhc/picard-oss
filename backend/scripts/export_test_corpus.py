#!/usr/bin/env python3
"""Backfill entities, export corpus snapshot, refresh corpus_constants benchmark IDs."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
SRC = ROOT / ".picard-data" / "picard.db"
DEST_DIR = BACKEND / "test" / "fixtures" / "corpus"
DEST = DEST_DIR / "picard-corpus.db"
CONSTANTS = BACKEND / "tests" / "corpus_constants.py"

BENCHMARK_TEXT = "The plaintiff claimed damages in the sum of £1,000."
WORKSPACE_ID = "eca7aebb-0b4d-433d-8e73-9144c04eb0d7"
DOCUMENT_ID = "b65e3196-7199-446e-a910-6476d23b7bc8"


def _checkpoint_wal(db_path: Path) -> None:
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()


def main() -> int:
    if not SRC.exists():
        print(f"Source not found: {SRC}", file=sys.stderr)
        return 1

    _checkpoint_wal(SRC)

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC, DEST)
    for suffix in ("-wal", "-shm"):
        side = Path(str(SRC) + suffix)
        if side.exists():
            shutil.copy2(side, Path(str(DEST) + suffix))

    from sqlalchemy import create_engine

    from app.db.bootstrap import run_migrations

    eng = create_engine(f"sqlite:///{DEST.resolve()}")
    run_migrations(eng)
    eng.dispose()

    subprocess.run(
        [
            sys.executable,
            str(BACKEND / "scripts" / "backfill_entities.py"),
            "--db",
            str(DEST),
        ],
        cwd=str(BACKEND),
        check=True,
    )
    import sqlite3

    conn = sqlite3.connect(DEST)
    row = conn.execute(
        "SELECT id FROM chunks WHERE document_id=? AND text_content LIKE ? LIMIT 1",
        (DOCUMENT_ID, f"%{BENCHMARK_TEXT}%"),
    ).fetchone()
    chunk_id = row[0] if row else ""
    conn.close()

    _write_constants(chunk_id)
    print(f"Exported corpus to {DEST}")
    print(f"Benchmark chunk_id: {chunk_id}")
    return 0


def _write_constants(benchmark_chunk_id: str) -> None:
    content = f'''"""Corpus constants for Chester baseline — refresh via export_test_corpus.py."""

WORKSPACE_ID = "{WORKSPACE_ID}"
DOCUMENT_ID = "{DOCUMENT_ID}"
DOCUMENT_NAME = "Chester v Municipality of Waverly .pdf"

# Primary eval benchmark (page 3) — damages claim line
BENCHMARK_LINE = "{BENCHMARK_TEXT}"
BENCHMARK_PAGE = 3
BENCHMARK_CHUNK_ID = "{benchmark_chunk_id}"
BENCHMARK_AMOUNT_CANONICAL = "1000_gbp"
BENCHMARK_PARTY_CANONICAL = "the plaintiff"

SIMPLE_QUERIES = {{
    "liability": {{"min_hits": 1}},
    "negligence": {{"min_hits": 1}},
    "Hambrook": {{"min_hits": 1}},
    "plaintiff claimed damages": {{"min_hits": 1, "gold_chunk_id": BENCHMARK_CHUNK_ID}},
}}

BENCHMARK_QUERIES = {{
    "exact": "plaintiff claimed damages in the sum of £1,000",
    "complex": "What damages sum did the plaintiff claim?",
    "paraphrase": "plaintiff damages sum claimed",
    "carp": "case context for supreme court with plaintiff damages of £1,000",
}}

# Page 3 has party + identifier + amount co-occurrence in Chester corpus
CARP_INTERSECTION_PAGE = 3

PARTY_ON_PAGE_3 = {{"supreme court", "stokes brothers", "high court", "refused", "the full court", "full court", "the plaintiff"}}
IDENTIFIER_ON_PAGE_3 = {{"refused", "high court"}}
AMOUNT_ON_PAGE_3 = {{"1000_gbp"}}
'''
    CONSTANTS.write_text(content)


if __name__ == "__main__":
    raise SystemExit(main())
