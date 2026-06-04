from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Chunk, Entity, EntityMention
from app.schemas import SearchHit
from app.services.excerpt_selector import has_amount_signal
from app.services.fts_search import parse_bbox


def chunks_from_entity_mentions(
    db: Session,
    workspace_id: str,
    document_ids: list[str] | None,
    *,
    entity_types: tuple[str, ...] = ("amount", "party", "identifier", "date"),
    limit: int = 24,
) -> list[SearchHit]:
    """Pull chunks tied to indexed entities — dynamic, not keyword rules."""
    if not document_ids:
        return []

    stmt = (
        select(Chunk, Entity.entity_type)
        .join(EntityMention, EntityMention.chunk_id == Chunk.id)
        .join(Entity, Entity.id == EntityMention.entity_id)
        .where(
            Entity.workspace_id == workspace_id,
            Entity.entity_type.in_(entity_types),
            Chunk.document_id.in_(document_ids),
        )
        .order_by(Chunk.page_number, Chunk.id)
        .limit(limit * 2)
    )
    rows = db.execute(stmt).all()
    seen: set[str] = set()
    hits: list[SearchHit] = []
    for chunk, entity_type in rows:
        if chunk.id in seen:
            continue
        seen.add(chunk.id)
        score = -1.0 if entity_type == "amount" else 0.0
        hits.append(
            SearchHit(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                page_number=chunk.page_number,
                text_content=chunk.text_content or "",
                heading_path=chunk.heading_path,
                section_key=chunk.section_key,
                bbox=parse_bbox(chunk.bbox_json),
                score=score,
            )
        )
        if len(hits) >= limit:
            break
    return hits


def chunks_from_entity_mentions_per_doc(
    db: Session,
    workspace_id: str,
    document_ids: list[str],
    *,
    entity_types: tuple[str, ...] = ("party", "amount", "identifier", "date"),
    per_doc_limit: int = 4,
) -> list[SearchHit]:
    """Fair per-document entity chunk quota (avoids one doc consuming global limit)."""
    merged: list[SearchHit] = []
    for doc_id in document_ids:
        doc_hits = chunks_from_entity_mentions(
            db,
            workspace_id,
            [doc_id],
            entity_types=entity_types,
            limit=per_doc_limit,
        )
        merged = merge_search_hits(merged, doc_hits)
    return merged


def merge_search_hits(existing: list[SearchHit], extra: list[SearchHit]) -> list[SearchHit]:
    by_id = {h.chunk_id: h for h in existing}
    for h in extra:
        if h.chunk_id not in by_id:
            by_id[h.chunk_id] = h
    return sorted(by_id.values(), key=lambda x: x.score)


def prioritize_overview_hits(hits: list[SearchHit]) -> list[SearchHit]:
    """Surface amount-bearing chunks first so citation indices favor them."""
    return sorted(
        hits,
        key=lambda h: (
            0 if has_amount_signal(h.text_content) else 1,
            h.page_number,
            h.score,
        ),
    )
