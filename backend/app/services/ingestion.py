from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document, Job
from app.db.session import SessionLocal, utc_now_iso
from app.services.chunk_builder import build_chunks_from_pdf, new_chunk_id
from app.services.entity_index import extract_entities_for_document
from app.services.storage import resolve_pdf_path

# liteparse / NER backends are not safe under concurrent native calls on macOS.
_executor = ThreadPoolExecutor(max_workers=1)
_parse_lock = threading.Lock()

RETRYABLE_STATUSES = frozenset({"pending", "parsing", "error"})


def _update_job(db: Session, job_id: str, **kwargs) -> None:
    job = db.get(Job, job_id)
    if not job:
        return
    for key, value in kwargs.items():
        setattr(job, key, value)
    job.updated_at = utc_now_iso()
    db.commit()


def _parse_document_sync(document_id: str, job_id: str) -> None:
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if not doc:
            _update_job(db, job_id, status="error", error="Document not found")
            return

        doc.parse_status = "parsing"
        _update_job(db, job_id, status="running", progress=0.1)
        db.commit()

        pdf_path = resolve_pdf_path(doc.local_path)
        from app.services.parse_plan import build_parse_plan

        plan = build_parse_plan(str(pdf_path))
        doc.text_source = plan.text_source
        doc.ocr_engine = "none" if not plan.ocr_enabled else plan.ocr_engine
        db.commit()

        with _parse_lock:
            chunks, page_count, parse_meta = build_chunks_from_pdf(str(pdf_path), plan=plan)

        doc.text_source = parse_meta.get("text_source")
        doc.ocr_engine = parse_meta.get("ocr_engine")

        db.execute(delete(Chunk).where(Chunk.document_id == document_id))
        db.flush()

        for built in chunks:
            db.add(
                Chunk(
                    id=new_chunk_id(),
                    document_id=document_id,
                    page_number=built.page_number,
                    chunk_type=built.chunk_type,
                    bbox_json=built.bbox_json,
                    text_content=built.text_content,
                    heading_path=built.heading_path,
                    section_key=built.section_key,
                    token_count=built.token_count,
                )
            )

        doc.page_count = page_count
        doc.parse_status = "done"
        doc.parse_error = None
        _update_job(
            db,
            job_id,
            status="done",
            progress=1.0,
            result_json=json.dumps({"chunk_count": len(chunks), **parse_meta}),
        )
        db.commit()

        extract_entities_for_document(db, document_id)
        from app.services.metadata_extractor import extract_metadata_for_document

        extract_metadata_for_document(db, document_id)
    except Exception as exc:
        db.rollback()
        doc = db.get(Document, document_id)
        if doc:
            doc.parse_status = "error"
            doc.parse_error = str(exc)
            db.commit()
        _update_job(db, job_id, status="error", error=str(exc))
    finally:
        db.close()


def _prepare_document_for_retry(db: Session, doc: Document) -> None:
    doc.parse_status = "pending"
    doc.parse_error = None
    doc.text_source = None
    doc.ocr_engine = None


def enqueue_parse_document(document_id: str) -> str:
    db = SessionLocal()
    try:
        job_id = str(uuid.uuid4())
        now = utc_now_iso()
        db.add(
            Job(
                id=job_id,
                job_type="parse",
                payload_json=json.dumps({"document_id": document_id}),
                status="pending",
                progress=0.0,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
        _executor.submit(_parse_document_sync, document_id, job_id)
        return job_id
    finally:
        db.close()


def retry_parse_document(document_id: str) -> str:
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if not doc:
            raise ValueError("Document not found")
        if doc.parse_status not in RETRYABLE_STATUSES:
            raise ValueError(f"Document is not retryable (status={doc.parse_status})")
        _prepare_document_for_retry(db, doc)
        db.commit()
    finally:
        db.close()
    return enqueue_parse_document(document_id)


def retry_stuck_documents(workspace_id: str) -> list[str]:
    db = SessionLocal()
    try:
        docs = db.scalars(
            select(Document).where(
                Document.workspace_id == workspace_id,
                Document.parse_status.in_(RETRYABLE_STATUSES),
            )
        ).all()
        retried: list[str] = []
        for doc in docs:
            _prepare_document_for_retry(db, doc)
            retried.append(doc.id)
        db.commit()
    finally:
        db.close()
    for document_id in retried:
        enqueue_parse_document(document_id)
    return retried


def recover_stuck_parsing_documents() -> int:
    """Re-queue documents left in 'parsing' after a crash or kill."""
    db = SessionLocal()
    try:
        docs = db.scalars(select(Document).where(Document.parse_status == "parsing")).all()
        recovered: list[str] = []
        for doc in docs:
            _prepare_document_for_retry(db, doc)
            recovered.append(doc.id)
        db.commit()
    finally:
        db.close()
    for document_id in recovered:
        enqueue_parse_document(document_id)
    return len(recovered)
