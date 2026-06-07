from __future__ import annotations

import json
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, TabularCell, TabularReview
from app.db.session import utc_now_iso
from app.schemas import TabularCellOut, TabularColumn, TabularReviewCreate, TabularReviewOut, TabularReviewSummary, TabularReviewUpdate


def _serialize_columns(columns: list[TabularColumn]) -> str:
    return json.dumps([c.model_dump() for c in columns])


def _parse_columns(raw: str) -> list[TabularColumn]:
    data = json.loads(raw)
    return [TabularColumn(**item) for item in data]


def _serialize_doc_ids(document_ids: list[str]) -> str:
    return json.dumps(document_ids)


def _parse_doc_ids(raw: str) -> list[str]:
    return json.loads(raw)


def _cell_to_out(cell: TabularCell) -> TabularCellOut:
    chunk_ids: list[str] = []
    if cell.source_chunk_ids_json:
        chunk_ids = json.loads(cell.source_chunk_ids_json)
    return TabularCellOut(
        id=cell.id,
        review_id=cell.review_id,
        document_id=cell.document_id,
        column_key=cell.column_key,
        summary=cell.summary,
        reasoning=cell.reasoning,
        flag=cell.flag,  # type: ignore[arg-type]
        status=cell.status,  # type: ignore[arg-type]
        source_chunk_ids=chunk_ids,
    )


def _seed_cells(
    db: Session,
    review_id: str,
    document_ids: list[str],
    columns: list[TabularColumn],
) -> None:
    for doc_id in document_ids:
        for col in columns:
            existing = db.scalar(
                select(TabularCell).where(
                    TabularCell.review_id == review_id,
                    TabularCell.document_id == doc_id,
                    TabularCell.column_key == col.key,
                )
            )
            if existing:
                continue
            db.add(
                TabularCell(
                    id=str(uuid.uuid4()),
                    review_id=review_id,
                    document_id=doc_id,
                    column_key=col.key,
                    status="pending",
                )
            )


def _sync_cells(db: Session, review: TabularReview, columns: list[TabularColumn], document_ids: list[str]) -> None:
    col_keys = {c.key for c in columns}
    doc_ids = set(document_ids)

    cells = db.scalars(select(TabularCell).where(TabularCell.review_id == review.id)).all()
    for cell in cells:
        if cell.document_id not in doc_ids or cell.column_key not in col_keys:
            db.delete(cell)

    _seed_cells(db, review.id, document_ids, columns)


def _validate_documents(db: Session, workspace_id: str, document_ids: list[str]) -> None:
    for doc_id in document_ids:
        doc = db.get(Document, doc_id)
        if not doc or doc.workspace_id != workspace_id:
            raise HTTPException(status_code=400, detail=f"Document {doc_id} not in workspace")


def create_review(db: Session, body: TabularReviewCreate) -> TabularReview:
    _validate_documents(db, body.workspace_id, body.document_ids)

    review_id = str(uuid.uuid4())
    review = TabularReview(
        id=review_id,
        workspace_id=body.workspace_id,
        title=body.title,
        columns_config_json=_serialize_columns(body.columns),
        document_ids_json=_serialize_doc_ids(body.document_ids),
        created_at=utc_now_iso(),
    )
    db.add(review)
    _seed_cells(db, review_id, body.document_ids, body.columns)
    db.commit()
    db.refresh(review)
    return review


def list_reviews(db: Session, workspace_id: str) -> list[TabularReviewSummary]:
    reviews = db.scalars(
        select(TabularReview)
        .where(TabularReview.workspace_id == workspace_id)
        .order_by(TabularReview.created_at.desc())
    ).all()
    out: list[TabularReviewSummary] = []
    for r in reviews:
        cols = _parse_columns(r.columns_config_json)
        docs = _parse_doc_ids(r.document_ids_json)
        out.append(
            TabularReviewSummary(
                id=r.id,
                workspace_id=r.workspace_id,
                title=r.title,
                column_count=len(cols),
                document_count=len(docs),
                created_at=r.created_at,
            )
        )
    return out


def get_review(db: Session, review_id: str) -> TabularReviewOut:
    review = db.get(TabularReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    columns = _parse_columns(review.columns_config_json)
    document_ids = _parse_doc_ids(review.document_ids_json)
    documents = db.scalars(select(Document).where(Document.id.in_(document_ids))).all() if document_ids else []
    doc_by_id = {d.id: d for d in documents}
    ordered_docs = [doc_by_id[did] for did in document_ids if did in doc_by_id]

    cells = db.scalars(select(TabularCell).where(TabularCell.review_id == review_id)).all()

    from app.schemas import DocumentOut

    return TabularReviewOut(
        id=review.id,
        workspace_id=review.workspace_id,
        title=review.title,
        columns=columns,
        document_ids=document_ids,
        documents=[DocumentOut.model_validate(d) for d in ordered_docs],
        cells=[_cell_to_out(c) for c in cells],
        created_at=review.created_at,
    )


def update_review(db: Session, review_id: str, body: TabularReviewUpdate) -> TabularReviewOut:
    review = db.get(TabularReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    columns = _parse_columns(review.columns_config_json)
    document_ids = _parse_doc_ids(review.document_ids_json)

    if body.title is not None:
        review.title = body.title
    if body.columns is not None:
        columns = body.columns
        review.columns_config_json = _serialize_columns(columns)
    if body.document_ids is not None:
        _validate_documents(db, review.workspace_id, body.document_ids)
        document_ids = body.document_ids
        review.document_ids_json = _serialize_doc_ids(document_ids)

    _sync_cells(db, review, columns, document_ids)
    db.commit()
    return get_review(db, review_id)


def delete_review(db: Session, review_id: str) -> None:
    review = db.get(TabularReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    db.delete(review)
    db.commit()


_PARTIES_COLUMN_HINTS = ("parties", "party", "counterpart")


def get_tabular_review_document_ids(db: Session, review_id: str) -> list[str]:
    review = db.get(TabularReview, review_id)
    if not review:
        return []
    return _parse_doc_ids(review.document_ids_json)


def count_tabular_review_documents(db: Session, review_id: str) -> int:
    return len(get_tabular_review_document_ids(db, review_id))


def _parties_column_keys(columns: list[TabularColumn]) -> list[str]:
    keys: list[str] = []
    for col in columns:
        key_cf = col.key.casefold()
        label_cf = col.label.casefold()
        if any(h in key_cf or h in label_cf for h in _PARTIES_COLUMN_HINTS):
            keys.append(col.key)
    return keys


def discover_tabular_listing_documents(
    db: Session,
    review_id: str,
    *,
    match_tokens: list[str],
) -> list[tuple[str, int]]:
    """Documents in a tabular review, scored by party-column match to target tokens."""
    review = db.get(TabularReview, review_id)
    if not review:
        return []

    document_ids = _parse_doc_ids(review.document_ids_json)
    if not document_ids:
        return []

    columns = _parse_columns(review.columns_config_json)
    party_keys = _parties_column_keys(columns)
    col_labels = {c.key: c.label for c in columns}

    cells = db.scalars(
        select(TabularCell).where(
            TabularCell.review_id == review_id,
            TabularCell.status == "done",
        )
    ).all()

    by_doc: dict[str, list[str]] = {doc_id: [] for doc_id in document_ids}
    for cell in cells:
        if cell.column_key in party_keys or not party_keys:
            text = (cell.summary or "").strip()
            if text:
                by_doc.setdefault(cell.document_id, []).append(text)
        elif party_keys:
            label = col_labels.get(cell.column_key, "").casefold()
            if any(h in label for h in _PARTIES_COLUMN_HINTS):
                text = (cell.summary or "").strip()
                if text:
                    by_doc.setdefault(cell.document_id, []).append(text)

    scored: list[tuple[str, int]] = []
    matched_any = False
    for doc_id in document_ids:
        texts = by_doc.get(doc_id, [])
        combined = " ".join(texts)
        if match_tokens and _tabular_text_matches(combined, match_tokens):
            scored.append((doc_id, 10 + len(texts)))
            matched_any = True
        elif not match_tokens:
            scored.append((doc_id, 1))

    if match_tokens and not matched_any:
        for cell in cells:
            text = (cell.summary or "").strip()
            if text and _tabular_text_matches(text, match_tokens):
                by_doc.setdefault(cell.document_id, []).append(text)
        for doc_id in document_ids:
            texts = by_doc.get(doc_id, [])
            if texts:
                scored.append((doc_id, 5 + len(texts)))
        matched_any = bool(scored)

    if not scored:
        scored = [(doc_id, 1) for doc_id in document_ids]

    return sorted(scored, key=lambda x: -x[1])


def _tabular_text_matches(text: str, tokens: list[str]) -> bool:
    if not text:
        return False
    cf = text.casefold()
    return any(tok in cf for tok in tokens)


def build_tabular_document_metadata_block(
    db: Session,
    review_id: str,
    document_id: str,
) -> str:
    """Per-document metadata from completed tabular cells for map-phase context."""
    review = db.get(TabularReview, review_id)
    if not review:
        return ""

    columns = _parse_columns(review.columns_config_json)
    col_labels = {c.key: c.label for c in columns}
    cells = db.scalars(
        select(TabularCell).where(
            TabularCell.review_id == review_id,
            TabularCell.document_id == document_id,
            TabularCell.status == "done",
        )
    ).all()
    if not cells:
        return ""

    lines = ["Tabular review metadata (structure only; cite facts from Sources with [N]):"]
    for cell in cells:
        label = col_labels.get(cell.column_key, cell.column_key)
        summary = (cell.summary or "").strip()
        if not summary:
            continue
        if len(summary) > 500:
            summary = summary[:500] + "…"
        lines.append(f"- **{label}:** {summary}")
    return "\n".join(lines) if len(lines) > 1 else ""


def build_tabular_chat_context(db: Session, review_id: str, max_chars: int = 8000) -> str:
    review = db.get(TabularReview, review_id)
    if not review:
        return ""
    columns = _parse_columns(review.columns_config_json)
    col_labels = {c.key: c.label for c in columns}
    document_ids = _parse_doc_ids(review.document_ids_json)
    docs = {d.id: d.file_name for d in db.scalars(select(Document).where(Document.id.in_(document_ids))).all()}

    cells = db.scalars(
        select(TabularCell).where(
            TabularCell.review_id == review_id,
            TabularCell.status == "done",
        )
    ).all()

    lines = [
        f"Active tabular review: {review.title}",
        "Use completed cell values below when answering. Corpus citations still use [N] markers.",
    ]
    for cell in cells[:80]:
        doc_name = docs.get(cell.document_id, cell.document_id)
        label = col_labels.get(cell.column_key, cell.column_key)
        summary = (cell.summary or "").strip()
        if len(summary) > 300:
            summary = summary[:300] + "…"
        lines.append(f"- {doc_name} | {label}: {summary}")

    text = "\n".join(lines)
    return text[:max_chars] if len(text) > max_chars else text


def _infer_format_from_idea(idea: str) -> str:
    lower = idea.casefold()
    if any(k in lower for k in ("date", "dated", "effective", "expir", "commencement")):
        return "date"
    if any(k in lower for k in ("yes or no", "whether", "permitted", "allowed")):
        return "yes_no"
    if any(k in lower for k in ("list each", "bullet", "parties", "enumerate")):
        return "bulleted_list"
    return "text"


def generate_column_prompt(
    label: str,
    fmt: str | None = None,
    *,
    idea: str | None = None,
) -> tuple[str, bool, str]:
    from app.services.pii_proxy import pii_enabled_for_settings_default, pii_request_scope

    with pii_request_scope(enabled=pii_enabled_for_settings_default()):
        return _generate_column_prompt_body(label, fmt, idea=idea)


def _generate_column_prompt_body(
    label: str,
    fmt: str | None = None,
    *,
    idea: str | None = None,
) -> tuple[str, bool, str]:
    from app.services.model_router import ModelRole, completion
    from app.tabular.presets import match_preset, preset_prompt_for_label

    resolved_fmt = fmt or "text"

    if not idea:
        preset = match_preset(label)
        if preset:
            return preset.prompt, True, preset.format

    if idea and len(idea.strip()) >= 3:
        import json
        import re

        system = (
            "You write concise extraction prompts for legal tabular review columns. "
            'Respond with JSON only: {"prompt": "...", "format": "text|bulleted_list|date|yes_no|number|currency"}. '
            "The prompt must instruct an LLM to extract from document chunks. "
            "If not found, say Not specified. Be concise."
        )
        user = f'Column title: "{label}"\nWhat to extract: {idea.strip()}'
        if fmt:
            user += f"\nPreferred format: {fmt}"
        raw = completion(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            role=ModelRole.SLM,
            response_format={"type": "json_object"},
        )
        if raw:
            text = raw.strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
            try:
                data = json.loads(text)
                prompt = str(data.get("prompt", "")).strip()
                suggested = str(data.get("format", resolved_fmt)).strip()
                valid = {
                    "text",
                    "bulleted_list",
                    "date",
                    "yes_no",
                    "number",
                    "currency",
                    "tag",
                    "percentage",
                    "monetary_amount",
                }
                if suggested not in valid:
                    suggested = _infer_format_from_idea(idea) if not fmt else resolved_fmt
                if prompt:
                    return prompt, False, suggested
            except (json.JSONDecodeError, TypeError):
                pass

        fallback_fmt = fmt or _infer_format_from_idea(idea)
        return (
            f'Extract the following from the document: {idea.strip()}. '
            f'Column title: "{label}". If not addressed, state "Not specified". Be concise.',
            False,
            fallback_fmt,
        )

    preset_prompt = preset_prompt_for_label(label)
    if preset_prompt:
        matched = match_preset(label)
        return preset_prompt, True, matched.format if matched else resolved_fmt

    system = (
        "You write concise extraction prompts for legal contract tabular review columns. "
        "Return only the prompt text, no preamble."
    )
    user = f'Column title: "{label}"\nFormat: {resolved_fmt}\nWrite a single extraction instruction for an LLM.'
    llm_prompt = completion(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        role=ModelRole.SLM,
    )
    if llm_prompt:
        return llm_prompt.strip(), False, resolved_fmt
    return (
        f'Extract information about "{label}" from the document. '
        'If not addressed, state "Not specified". Be concise.',
        False,
        resolved_fmt,
    )
