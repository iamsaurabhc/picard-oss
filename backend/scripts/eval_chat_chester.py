#!/usr/bin/env python3
"""End-to-end Chester chat eval — retrieval SSE + reference quality + citation markers."""

from __future__ import annotations

import asyncio
import json
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


FIXTURES = [
    {
        "id": "chat_damages",
        "message": "What damages did the plaintiff claim?",
        "expect_refused": False,
        "expect_gold_chunk": BENCHMARK_CHUNK_ID,
        "expect_marker": True,
    },
    {
        "id": "chat_chester_nl",
        "message": "List all case details involving Chester v Waverley",
        "expect_refused": False,
        "expect_substantive_top4": True,
        "expect_marker": True,
    },
    {
        "id": "chat_ab01",
        "message": "What is the liability cap in the nonexistent contract?",
        "expect_refused": True,
        "expect_marker": False,
    },
]


async def _run_case(db, session_id: str, case: dict) -> dict:
    settings.enable_llm_query_understanding = False
    settings.enable_context_ranker = False

    body = ChatStreamRequest(
        session_id=session_id,
        workspace_id=WORKSPACE_ID,
        message=case["message"],
        document_ids=[DOCUMENT_ID],
        retrieval_mode="simple",
    )
    events: list[dict] = []
    async for event in stream_chat(db, body):
        events.append(event)

    retrieval = next((e for e in events if e.get("event") == "retrieval"), {})
    refs_event = next((e for e in events if e.get("event") == "references"), {})
    content = "".join(e.get("delta", "") for e in events if e.get("event") == "content")

    hit_ids = []
    diagnostics = retrieval.get("diagnostics") or {}
    if diagnostics.get("fts_query"):
        pass

    refs = refs_event.get("references") or []
    chunk_ids = [r.get("chunk_id") for r in refs]
    preview_ok = all(
        (r.get("preview") or r.get("pinpoint_quote") or "") for r in refs
    ) if refs else True

    passed = True
    reasons: list[str] = []

    if case.get("expect_refused"):
        if not refs_event.get("refused"):
            passed = False
            reasons.append("expected refuse")
    else:
        if refs_event.get("refused"):
            passed = False
            reasons.append("unexpected refuse")

    if case.get("expect_gold_chunk"):
        if case["expect_gold_chunk"] not in chunk_ids:
            passed = False
            reasons.append(f"missing gold chunk {case['expect_gold_chunk']}")

    if case.get("expect_marker") and "[" not in content:
        passed = False
        reasons.append("missing [N] marker in answer")

    if case.get("expect_substantive_top4"):
        previews = [r.get("preview", "") for r in refs[:4]]
        if previews and all(len(p.strip()) < 40 for p in previews):
            passed = False
            reasons.append("header-only top references")

    if refs and not preview_ok:
        passed = False
        reasons.append("empty reference preview")

    return {
        "case_id": case["id"],
        "passed": passed,
        "reasons": reasons,
        "refused": refs_event.get("refused"),
        "chunk_ids": chunk_ids,
        "content_len": len(content),
        "ranked_count": diagnostics.get("ranked_count"),
    }


async def main() -> int:
    path = resolve_corpus_db_path()
    if not path:
        print("No corpus DB found", file=sys.stderr)
        return 1

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

    ws = db.get(Workspace, WORKSPACE_ID)
    if not ws:
        print("Chester workspace not in corpus DB", file=sys.stderr)
        return 1

    now = utc_now_iso()
    session = ChatSession(
        id=str(uuid.uuid4()),
        workspace_id=WORKSPACE_ID,
        title="eval",
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    db.commit()

    # Mock LLM synthesis for deterministic eval
    async def fake_stream(*args, **kwargs):
        yield "The plaintiff claimed damages [1]."

    import app.services.chat as chat_mod

    chat_mod.stream_completion = fake_stream

    results = []
    for case in FIXTURES:
        results.append(await _run_case(db, session.id, case))

    report = {"cases": results, "pass": all(r["passed"] for r in results)}
    print(json.dumps(report, indent=2))
    db.close()
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
