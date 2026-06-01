#!/usr/bin/env python3
"""Generate synthetic scale DB for CARP perf tests (subset mode for CI)."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db.bootstrap import run_init_sql
from app.db.models import Base, Chunk, Document, Entity, PageEntity, Workspace
from app.db.session import utc_now_iso


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=1000)
    parser.add_argument("--out", type=Path, default=Path("backend/test/fixtures/corpus/scale-corpus.db"))
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        args.out.unlink()

    engine = create_engine(f"sqlite:///{args.out}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    run_init_sql(engine)
    Base.metadata.create_all(bind=engine)
    now = utc_now_iso()
    ws_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())

    with Session(engine) as db:
        db.add(Workspace(id=ws_id, name="Scale", matter_ref=None, created_at=now, updated_at=now))
        db.add(
            Document(
                id=doc_id,
                workspace_id=ws_id,
                file_name="scale.pdf",
                local_path="scale.pdf",
                content_hash="scale",
                page_count=args.pages,
                parse_status="done",
                created_at=now,
            )
        )
        party = Entity(
            id=str(uuid.uuid4()),
            workspace_id=ws_id,
            entity_type="party",
            canonical_value="abc",
            display_value="ABC",
        )
        date_e = Entity(
            id=str(uuid.uuid4()),
            workspace_id=ws_id,
            entity_type="date",
            canonical_value="2019-05-18",
            display_value="18/05/2019",
        )
        cond = Entity(
            id=str(uuid.uuid4()),
            workspace_id=ws_id,
            entity_type="condition",
            canonical_value="condition c",
            display_value="Condition C",
        )
        db.add_all([party, date_e, cond])
        db.flush()

        intersect_pages = set(range(1, 9))
        for page in range(1, args.pages + 1):
            chunk_id = str(uuid.uuid4())
            text = f"Page {page} content party ABC date 18/05/2019 condition c"
            db.add(
                Chunk(
                    id=chunk_id,
                    document_id=doc_id,
                    page_number=page,
                    chunk_type="paragraph",
                    bbox_json=json.dumps({"x0": 0, "y0": 0, "x1": 1, "y1": 0.1}),
                    text_content=text,
                    heading_path=None,
                    section_key=None,
                    token_count=10,
                )
            )
            if page in intersect_pages:
                for ent in (party, date_e, cond):
                    db.add(
                        PageEntity(
                            document_id=doc_id,
                            page_number=page,
                            entity_id=ent.id,
                            mention_count=1,
                        )
                    )
            elif page % 100 == 0:
                db.add(PageEntity(document_id=doc_id, page_number=page, entity_id=party.id, mention_count=1))
        db.commit()

    print(f"Created {args.out} with {args.pages} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
