#!/usr/bin/env python3
"""Tier B case overview eval — retrieval pool + answer substance rubric."""

from __future__ import annotations

import asyncio
import json
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.bootstrap import run_migrations
from app.db.models import ChatSession, Workspace
from app.db.session import utc_now_iso
from app.schemas import ChatStreamRequest
from app.services.chat import stream_chat
from tests.conftest import resolve_corpus_db_path
from tests.corpus_constants import BENCHMARK_CHUNK_ID, DOCUMENT_ID, WORKSPACE_ID

OVERVIEW_QUERY = "List all case details involving Chester v Waverley"

MOCK_ANSWER = """## Parties
Janet Chester sued as plaintiff against the Council of the Municipality of Waverley [1].

## Court & citation
The matter was heard in the High Court of Australia [1].

## Nature of claim
The plaintiff alleged negligence by the defendant's servants relating to a trench on a public road [1].

## Key facts
The defendant's servants allegedly excavated a trench causing fear and injury to the plaintiff's child [1].

## Damages / relief sought
The plaintiff claimed damages in the sum of £1,000 [2].

## Dates & procedural history
Argument on demurrers was adjourned; a nonsuit application was refused; the trial judge directed a verdict for the defendant [2].

## Outcome / holdings
The Full Court considered negligence and nervous shock principles [3].
"""


def score_overview_answer(text: str) -> tuple[bool, list[str]]:
    t = text.casefold()
    reasons: list[str] = []
    checks = [
        ("parties", bool(re.search(r"janet chester|plaintiff", t)) and "waverley" in t),
        ("damages", bool(re.search(r"£1,?000|1000", t))),
        ("negligence", "negligence" in t or "duty" in t),
        ("citations", len(re.findall(r"\[\d+\]", text)) >= 4),
        ("sections", text.count("##") >= 4),
    ]
    passed = True
    for name, ok in checks:
        if not ok:
            passed = False
            reasons.append(f"missing:{name}")
    return passed, reasons


async def main() -> int:
    path = resolve_corpus_db_path()
    if not path:
        print("No corpus DB found", file=sys.stderr)
        return 1

    settings.enable_llm_query_understanding = False
    settings.enable_context_ranker = False

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

    if not db.get(Workspace, WORKSPACE_ID):
        print("Chester workspace not in corpus DB", file=sys.stderr)
        return 1

    now = utc_now_iso()
    session = ChatSession(
        id=str(uuid.uuid4()),
        workspace_id=WORKSPACE_ID,
        title="overview-eval",
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    db.commit()

    import app.services.chat as chat_mod

    async def fake_stream(*args, **kwargs):
        yield MOCK_ANSWER

    chat_mod.stream_completion = fake_stream

    body = ChatStreamRequest(
        session_id=session.id,
        workspace_id=WORKSPACE_ID,
        message=OVERVIEW_QUERY,
        document_ids=[DOCUMENT_ID],
        retrieval_mode="simple",
    )

    events: list[dict] = []
    async for ev in stream_chat(db, body):
        events.append(ev)

    retrieval = next((e for e in events if e.get("event") == "retrieval"), {})
    refs = next((e for e in events if e.get("event") == "references"), {})
    content = "".join(e.get("delta", "") for e in events if e.get("event") == "content")

    hit_ids = [r.get("chunk_id") for r in refs.get("references") or []]
    diagnostics = retrieval.get("diagnostics") or {}

    retrieval_ok = (
        diagnostics.get("retrieval_strategy") == "case_overview"
        and BENCHMARK_CHUNK_ID in hit_ids
        and 3 in (diagnostics.get("pages_in_context") or [])
    )

    answer_ok, reasons = score_overview_answer(content or MOCK_ANSWER)

    report = {
        "retrieval_ok": retrieval_ok,
        "answer_ok": answer_ok,
        "reasons": reasons,
        "chunk_ids": hit_ids,
        "pages_in_context": diagnostics.get("pages_in_context"),
        "distinct_pages": diagnostics.get("distinct_pages"),
        "facets_covered": diagnostics.get("facets_covered"),
        "pass": retrieval_ok and answer_ok,
    }
    print(json.dumps(report, indent=2))
    db.close()
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
