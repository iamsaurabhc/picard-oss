from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.db.models import Chunk, Document, Job
from app.db.session import SessionLocal, get_db

router = APIRouter(tags=["documents"])

POLL_INTERVAL_SEC = 0.5
TERMINAL_STATUSES = frozenset({"done", "error"})


def _latest_parse_job(db: Session, document_id: str) -> Job | None:
    jobs = db.scalars(
        select(Job)
        .where(Job.job_type == "parse")
        .order_by(Job.created_at.desc())
    ).all()
    for job in jobs:
        try:
            payload = json.loads(job.payload_json or "{}")
        except json.JSONDecodeError:
            continue
        if payload.get("document_id") == document_id:
            return job
    return None


def _chunk_count(db: Session, document_id: str) -> int:
    return db.scalar(
        select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
    ) or 0


async def _document_status_events(document_id: str):
    last_status: str | None = None
    last_progress: float | None = None
    emitted_ready = False

    while True:
        db = SessionLocal()
        try:
            doc = db.get(Document, document_id)
            if not doc:
                yield {"event": "error", "data": json.dumps({"detail": "Document not found"})}
                return

            job = _latest_parse_job(db, document_id)
            progress = float(job.progress) if job else None
            payload: dict = {
                "document_id": document_id,
                "parse_status": doc.parse_status,
            }
            if progress is not None:
                payload["progress"] = progress
            if doc.parse_error:
                payload["parse_error"] = doc.parse_error

            status_changed = doc.parse_status != last_status or progress != last_progress
            if status_changed:
                last_status = doc.parse_status
                last_progress = progress
                yield {"event": "status", "data": json.dumps(payload)}

            if doc.parse_status == "parsing":
                yield {
                    "event": "indexing",
                    "data": json.dumps({"document_id": document_id, "phase": "parsing"}),
                }

            if doc.parse_status == "error":
                yield {
                    "event": "error",
                    "data": json.dumps({"detail": doc.parse_error or "Parse failed"}),
                }
                return

            if doc.parse_status == "done" and not emitted_ready:
                emitted_ready = True
                yield {
                    "event": "indexing",
                    "data": json.dumps({"document_id": document_id, "phase": "entities"}),
                }
                yield {
                    "event": "ready",
                    "data": json.dumps(
                        {
                            "document_id": document_id,
                            "chunk_count": _chunk_count(db, document_id),
                            "page_count": doc.page_count or 0,
                        }
                    ),
                }
                return
        finally:
            db.close()

        await asyncio.sleep(POLL_INTERVAL_SEC)


@router.get("/documents/{document_id}/status/stream")
async def document_status_stream(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    async def event_generator():
        async for event in _document_status_events(document_id):
            yield event

    return EventSourceResponse(event_generator(), ping=5)
