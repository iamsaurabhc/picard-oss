from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Chunk, Entity, EntityMention
from app.schemas import TabularColumn
from app.services.fts_search import FtsHit, _chunk_is_informative, fts_search
from app.tabular.presets import RetrievalPolicy, retrieval_policy_for_column


def _chunk_to_hit(chunk: Chunk, score: float = 0.0) -> FtsHit:
    return FtsHit(
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        page_number=chunk.page_number,
        text_content=chunk.text_content or "",
        heading_path=chunk.heading_path,
        section_key=chunk.section_key,
        bbox_json=chunk.bbox_json,
        score=score,
    )


def _early_page_chunks(
    db: Session,
    *,
    document_id: str,
    max_page: int,
    limit: int = 4,
) -> list[FtsHit]:
    rows = db.scalars(
        select(Chunk)
        .where(
            Chunk.document_id == document_id,
            Chunk.page_number <= max_page,
        )
        .order_by(Chunk.page_number, Chunk.id)
    ).all()
    hits: list[FtsHit] = []
    for chunk in rows:
        if not _chunk_is_informative(chunk.text_content):
            continue
        hits.append(_chunk_to_hit(chunk, score=-10.0 + chunk.page_number))
        if len(hits) >= limit:
            break
    return hits


def _heading_hint_chunks(
    db: Session,
    *,
    document_id: str,
    heading_hint: str,
    limit: int = 3,
) -> list[FtsHit]:
    pattern = f"%{heading_hint}%"
    rows = db.scalars(
        select(Chunk)
        .where(
            Chunk.document_id == document_id,
            or_(
                Chunk.heading_path.ilike(pattern),
                Chunk.text_content.ilike(pattern),
            ),
        )
        .order_by(Chunk.page_number, Chunk.id)
        .limit(limit * 2)
    ).all()
    hits: list[FtsHit] = []
    for chunk in rows:
        if not _chunk_is_informative(chunk.text_content):
            continue
        hits.append(_chunk_to_hit(chunk, score=-3.0))
        if len(hits) >= limit:
            break
    return hits


def _entity_index_chunks(
    db: Session,
    *,
    document_id: str,
    workspace_id: str,
    entity_types: tuple[str, ...],
    limit: int = 4,
) -> list[FtsHit]:
    stmt = (
        select(Chunk)
        .join(EntityMention, EntityMention.chunk_id == Chunk.id)
        .join(Entity, Entity.id == EntityMention.entity_id)
        .where(
            Chunk.document_id == document_id,
            Entity.workspace_id == workspace_id,
            Entity.entity_type.in_(entity_types),
        )
        .order_by(Chunk.page_number, Chunk.id)
        .limit(limit * 2)
    )
    seen: set[str] = set()
    hits: list[FtsHit] = []
    for chunk in db.scalars(stmt).all():
        if chunk.id in seen:
            continue
        seen.add(chunk.id)
        if not _chunk_is_informative(chunk.text_content):
            continue
        hits.append(_chunk_to_hit(chunk, score=-5.0))
        if len(hits) >= limit:
            break
    return hits


def _merge_hits(ordered_groups: list[list[FtsHit]], max_chunks: int) -> list[FtsHit]:
    seen: set[str] = set()
    out: list[FtsHit] = []
    for group in ordered_groups:
        for hit in group:
            if hit.chunk_id in seen:
                continue
            seen.add(hit.chunk_id)
            out.append(hit)
            if len(out) >= max_chunks:
                return out
    return out


def gather_cell_chunks(
    db: Session,
    *,
    document_id: str,
    workspace_id: str,
    column: TabularColumn,
    policy: RetrievalPolicy | None = None,
) -> list[FtsHit]:
    policy = policy or retrieval_policy_for_column(column.key)
    groups: list[list[FtsHit]] = []

    for strategy in policy.strategies:
        if strategy == "early_pages":
            groups.append(
                _early_page_chunks(
                    db,
                    document_id=document_id,
                    max_page=policy.early_page_count,
                    limit=4,
                )
            )
        elif strategy == "entity_index":
            groups.append(
                _entity_index_chunks(
                    db,
                    document_id=document_id,
                    workspace_id=workspace_id,
                    entity_types=policy.entity_types,
                    limit=4,
                )
            )
        elif strategy == "fts":
            fts_query = policy.fts_seed_query or column.prompt
            groups.append(
                fts_search(
                    db,
                    query=fts_query,
                    workspace_id=workspace_id,
                    document_ids=[document_id],
                    top_k=4,
                    max_chunks_per_doc=4,
                )
            )

    if policy.heading_hint:
        groups.insert(
            0,
            _heading_hint_chunks(
                db,
                document_id=document_id,
                heading_hint=policy.heading_hint,
                limit=3,
            ),
        )

    return _merge_hits(groups, policy.max_chunks)


def gather_cell_chunks_retry_parties(
    db: Session,
    *,
    document_id: str,
    workspace_id: str,
    column: TabularColumn,
) -> list[FtsHit]:
    policy = RetrievalPolicy(
        strategies=("early_pages", "entity_index"),
        early_page_count=5,
        max_chunks=8,
        entity_types=("party",),
    )
    return gather_cell_chunks(
        db,
        document_id=document_id,
        workspace_id=workspace_id,
        column=column,
        policy=policy,
    )
