from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import AsyncIterator, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, TabularCell, TabularReview
from app.db.session import SessionLocal
from app.schemas import TabularBatchGenerateRequest, TabularCellOut, TabularColumn
from app.services import tabular as tabular_svc
from app.services.fts_search import FtsHit
from app.services.model_router import ModelRole, completion
from app.services.tabular_grounding import (
    build_tabular_grounding,
    document_doc_type,
    indexed_parties_for_document,
    metadata_for_column,
    parties_summary_misses_index,
)
from app.services.tabular_retrieval import (
    gather_cell_chunks,
    gather_cell_chunks_retry_parties,
)
from app.services.tabular_validate import (
    enforce_format_summary,
    format_instruction,
    is_litigation_na_column,
    litigation_na_summary,
    needs_metadata_retry,
    needs_shorter_retry,
)
from app.tabular.presets import prompt_for_column

logger = logging.getLogger(__name__)

CITATION_RE = re.compile(r"\[\[page:(\d+)\|\|quote:([^\]]+)\]\]")

CellFlag = Literal["green", "grey", "yellow", "red"]


class TabularCellExtraction(BaseModel):
    summary: str
    reasoning: str
    chunk_ids: list[str] = Field(default_factory=list)
    flag: CellFlag = "green"


def _parse_columns(raw: str) -> list[TabularColumn]:
    data = json.loads(raw)
    return [TabularColumn(**item) for item in data]


def _column_by_key(columns: list[TabularColumn], key: str) -> TabularColumn | None:
    return next((c for c in columns if c.key == key), None)


def _excerpt_for_citation(text: str, max_len: int = 120) -> str:
    cleaned = (text or "").strip().replace("\n", " ")
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len].rstrip() + "…"


def _embed_citations(summary: str, chunk_ids: list[str], hits_by_id: dict[str, FtsHit]) -> str:
    if not chunk_ids or CITATION_RE.search(summary):
        return summary
    markers: list[str] = []
    for cid in chunk_ids[:3]:
        hit = hits_by_id.get(cid)
        if not hit:
            continue
        quote = _excerpt_for_citation(hit.text_content)
        markers.append(f"[[page:{hit.page_number}||quote:{quote}]]")
    if not markers:
        return summary
    return f"{summary} {' '.join(markers)}".strip()


def _coerce_summary(value: object) -> str:
    """LLMs often return bulleted_list summaries as JSON arrays instead of a string."""
    if value is None:
        return ""
    if isinstance(value, list):
        lines: list[str] = []
        for item in value:
            s = str(item).strip()
            if not s:
                continue
            lines.append(s if s.startswith("-") else f"- {s}")
        return "\n".join(lines)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _normalize_extraction_payload(data: dict) -> dict:
    out = dict(data)
    if "summary" in out:
        out["summary"] = _coerce_summary(out["summary"])
    if "reasoning" in out and not isinstance(out.get("reasoning"), str):
        out["reasoning"] = str(out["reasoning"])
    chunk_ids = out.get("chunk_ids")
    if isinstance(chunk_ids, list):
        out["chunk_ids"] = [str(cid) for cid in chunk_ids if cid]
    return out


def _parse_llm_json(raw: str | None) -> TabularCellExtraction | None:
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        return TabularCellExtraction.model_validate(_normalize_extraction_payload(data))
    except json.JSONDecodeError as exc:
        logger.warning("tabular JSON parse failed: %s", exc)
        return None
    except ValidationError as exc:
        logger.warning("tabular JSON parse failed: %s", exc)
        return None


def _build_messages(
    column: TabularColumn,
    hits: list[FtsHit],
    doc_name: str,
    *,
    instruction: str,
    grounding: str = "",
    strict_parties: bool = False,
    strict_metadata: bool = False,
    shorter: bool = False,
) -> list[dict[str, str]]:
    context_parts: list[str] = []
    allowed_ids: list[str] = []
    for i, hit in enumerate(hits, start=1):
        allowed_ids.append(hit.chunk_id)
        context_parts.append(
            f"[Chunk {i}] id={hit.chunk_id} page={hit.page_number}\n{hit.text_content[:2000]}"
        )
    context = "\n\n".join(context_parts) if context_parts else "(no matching chunks)"

    system = (
        "You extract structured values for a legal tabular review cell. "
        "Respond with JSON only: "
        '{"summary": "...", "reasoning": "...", "chunk_ids": ["uuid"], "flag": "green|grey|yellow|red"}. '
        "Use chunk_ids only from the provided chunks. "
        "flag=green when confident, yellow when partial, red when contradictory, grey when not found. "
        f"Output format rule: {format_instruction(column.format)}"
    )
    if strict_parties:
        system += (
            " For parties: list every name in the indexed party list and early-page chunks. "
            "Never answer Not specified when indexed parties exist."
        )
    if strict_metadata:
        system += (
            " Indexed metadata tags are authoritative — use them in summary even if chunks are sparse."
        )
    if shorter:
        system += " Prior answer was too long — shorten summary to meet the format word limit."

    user_parts = [
        f"Document: {doc_name}",
        f"Column: {column.label}",
        f"Format: {column.format}",
        f"Instruction: {instruction}",
    ]
    if grounding:
        user_parts.append(grounding)
    user_parts.extend([
        f"Source chunks:\n{context}",
        f"Allowed chunk_ids: {json.dumps(allowed_ids)}",
    ])
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n\n".join(user_parts)}]


def _run_extraction(
    *,
    column: TabularColumn,
    hits: list[FtsHit],
    doc_name: str,
    instruction: str,
    grounding: str,
    strict_parties: bool = False,
    strict_metadata: bool = False,
    shorter: bool = False,
) -> TabularCellExtraction | None:
    messages = _build_messages(
        column,
        hits,
        doc_name,
        instruction=instruction,
        grounding=grounding,
        strict_parties=strict_parties,
        strict_metadata=strict_metadata,
        shorter=shorter,
    )
    raw = completion(
        messages=messages,
        role=ModelRole.LLM,
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    parsed = _parse_llm_json(raw)
    if not parsed:
        raw_retry = completion(messages=messages, role=ModelRole.LLM, temperature=0.0)
        parsed = _parse_llm_json(raw_retry)
    return parsed


def _finalize_cell(
    cell: TabularCell,
    parsed: TabularCellExtraction,
    hits: list[FtsHit],
    *,
    column: TabularColumn,
) -> None:
    hits_by_id = {h.chunk_id: h for h in hits}
    allowed = {h.chunk_id for h in hits}
    valid_chunk_ids = [cid for cid in parsed.chunk_ids if cid in allowed]
    if not valid_chunk_ids and hits:
        valid_chunk_ids = [hits[0].chunk_id]

    summary = enforce_format_summary(parsed.summary, column.format)
    summary = _embed_citations(summary, valid_chunk_ids, hits_by_id)

    cell.summary = summary
    cell.reasoning = parsed.reasoning
    cell.flag = parsed.flag
    cell.status = "done"
    cell.source_chunk_ids_json = json.dumps(valid_chunk_ids)


def extract_cell(
    db: Session,
    *,
    cell: TabularCell,
    review: TabularReview,
    column: TabularColumn,
) -> TabularCellOut:
    doc = db.get(Document, cell.document_id)
    if not doc:
        cell.status = "error"
        cell.flag = "red"
        cell.summary = "Document not found"
        db.commit()
        return tabular_svc._cell_to_out(cell)

    cell.status = "generating"
    db.commit()

    doc_type = document_doc_type(db, cell.document_id, doc.file_name)
    if is_litigation_na_column(doc_type, column.key):
        cell.summary = litigation_na_summary(column.key)
        cell.reasoning = f"Document type is {doc_type}; column is contract-oriented."
        cell.flag = "grey"
        cell.status = "done"
        cell.source_chunk_ids_json = json.dumps([])
        db.commit()
        db.refresh(cell)
        return tabular_svc._cell_to_out(cell)

    instruction = prompt_for_column(column, doc_type)
    hits = gather_cell_chunks(
        db,
        document_id=cell.document_id,
        workspace_id=review.workspace_id,
        column=column,
    )
    grounding = build_tabular_grounding(
        db,
        document_id=cell.document_id,
        workspace_id=review.workspace_id,
        column_key=column.key,
        file_name=doc.file_name,
    )
    metadata = metadata_for_column(db, cell.document_id, column.key)

    parsed = _run_extraction(
        column=column,
        hits=hits,
        doc_name=doc.file_name,
        instruction=instruction,
        grounding=grounding,
        strict_parties=False,
    )

    indexed_parties: list[str] = []
    if column.key == "parties":
        indexed_parties = indexed_parties_for_document(
            db, cell.document_id, review.workspace_id
        )
        if parsed and parties_summary_misses_index(parsed.summary, indexed_parties):
            retry_hits = gather_cell_chunks_retry_parties(
                db,
                document_id=cell.document_id,
                workspace_id=review.workspace_id,
                column=column,
            )
            if retry_hits:
                hits = retry_hits
            parsed = _run_extraction(
                column=column,
                hits=hits,
                doc_name=doc.file_name,
                instruction=instruction,
                grounding=grounding,
                strict_parties=True,
            )
            if parsed and parties_summary_misses_index(parsed.summary, indexed_parties):
                parsed.flag = "yellow"

    if parsed and needs_metadata_retry(parsed.summary, column.key, metadata):
        parsed = _run_extraction(
            column=column,
            hits=hits,
            doc_name=doc.file_name,
            instruction=instruction,
            grounding=grounding,
            strict_metadata=True,
        )
        if parsed:
            parsed.flag = "yellow"

    if parsed and needs_shorter_retry(parsed.summary, column):
        shorter_parsed = _run_extraction(
            column=column,
            hits=hits,
            doc_name=doc.file_name,
            instruction=instruction,
            grounding=grounding,
            shorter=True,
        )
        if shorter_parsed:
            parsed = shorter_parsed

    if not parsed:
        cell.status = "error"
        cell.flag = "grey"
        cell.summary = "Extraction failed"
        cell.reasoning = None
        cell.source_chunk_ids_json = json.dumps([])
        db.commit()
        db.refresh(cell)
        return tabular_svc._cell_to_out(cell)

    _finalize_cell(cell, parsed, hits, column=column)
    db.commit()
    db.refresh(cell)
    return tabular_svc._cell_to_out(cell)


def regenerate_cell(db: Session, cell_id: str) -> TabularCellOut:
    cell = db.get(TabularCell, cell_id)
    if not cell:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Cell not found")
    review = db.get(TabularReview, cell.review_id)
    if not review:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Review not found")
    columns = _parse_columns(review.columns_config_json)
    column = _column_by_key(columns, cell.column_key)
    if not column:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Column not found for cell")
    return extract_cell(db, cell=cell, review=review, column=column)


def _cells_to_process(
    db: Session,
    review: TabularReview,
    body: TabularBatchGenerateRequest,
) -> list[TabularCell]:
    document_ids = json.loads(review.document_ids_json)
    if body.document_ids:
        document_ids = [d for d in document_ids if d in body.document_ids]

    q = select(TabularCell).where(
        TabularCell.review_id == review.id,
        TabularCell.document_id.in_(document_ids),
    )
    if body.column_keys:
        q = q.where(TabularCell.column_key.in_(body.column_keys))
    if body.only_pending:
        q = q.where(TabularCell.status.in_(("pending", "error")))

    return list(db.scalars(q).all())


async def stream_batch_generation(
    review_id: str,
    body: TabularBatchGenerateRequest,
) -> AsyncIterator[dict]:
    db = SessionLocal()
    try:
        review = db.get(TabularReview, review_id)
        if not review:
            yield {"event": "error", "detail": "Review not found"}
            return

        columns = _parse_columns(review.columns_config_json)
        cells = _cells_to_process(db, review, body)
        total = len(cells)
        yield {"event": "batch_start", "review_id": review_id, "total_cells": total}

        sem = asyncio.Semaphore(2)
        done_count = 0
        error_count = 0

        async def process_one(cell_id: str) -> dict:
            async with sem:
                worker_db = SessionLocal()
                try:
                    cell = worker_db.get(TabularCell, cell_id)
                    if not cell:
                        return {"event": "cell_error", "cell_id": cell_id, "error": "Cell not found"}
                    review_row = worker_db.get(TabularReview, review_id)
                    if not review_row:
                        return {"event": "cell_error", "cell_id": cell_id, "error": "Review not found"}
                    column = _column_by_key(columns, cell.column_key)
                    if not column:
                        return {"event": "cell_error", "cell_id": cell_id, "error": "Unknown column"}
                    await asyncio.to_thread(
                        extract_cell,
                        worker_db,
                        cell=cell,
                        review=review_row,
                        column=column,
                    )
                    worker_db.refresh(cell)
                    out = tabular_svc._cell_to_out(cell)
                    if cell.status == "error":
                        return {
                            "event": "cell_error",
                            "cell_id": cell.id,
                            "error": cell.summary or "Extraction failed",
                        }
                    return {"event": "cell_done", "cell": out.model_dump()}
                finally:
                    worker_db.close()

        tasks = []
        for cell in cells:
            yield {
                "event": "cell_start",
                "cell_id": cell.id,
                "document_id": cell.document_id,
                "column_key": cell.column_key,
            }
            tasks.append(asyncio.create_task(process_one(cell.id)))

        for task in asyncio.as_completed(tasks):
            result = await task
            if result["event"] == "cell_done":
                done_count += 1
            elif result["event"] == "cell_error":
                error_count += 1
            yield result

        yield {
            "event": "batch_complete",
            "review_id": review_id,
            "done": done_count,
            "errors": error_count,
        }
    finally:
        db.close()
