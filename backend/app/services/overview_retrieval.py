from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.config import settings
from app.schemas import SearchHit
from app.services.planned_retrieval import (
    PlannedRetrievalConfig,
    planned_retrieve_with_progress,
)
from app.services.query_understanding import QueryUnderstanding
from app.services.retrieval_progress import RetrievalProgressEmitter, consume_retrieval_generator


def overview_retrieve_with_progress(
    db: Session,
    understanding: QueryUnderstanding,
    *,
    workspace_id: str,
    document_ids: list[str] | None = None,
    query: str = "",
    emitter: RetrievalProgressEmitter | None = None,
) -> Iterator[dict]:
    """Multi-pass retrieval optimized for case overview breadth."""
    config = PlannedRetrievalConfig(
        pool_k=settings.chat_overview_pool_k,
        max_per_page=settings.chat_overview_max_chunks_per_page,
        min_distinct_pages=3,
        pin_best_default=True,
        anchor_top_k=settings.chat_overview_pool_k // 2,
        entity_boost=True,
        early_page_bias=True,
        strategy="case_overview",
    )
    return (yield from planned_retrieve_with_progress(
        db,
        understanding,
        workspace_id=workspace_id,
        document_ids=document_ids,
        query=query,
        config=config,
        emitter=emitter,
    ))


def overview_retrieve(
    db: Session,
    understanding: QueryUnderstanding,
    *,
    workspace_id: str,
    document_ids: list[str] | None = None,
    query: str = "",
) -> tuple[list[SearchHit], dict]:
    """Multi-pass retrieval optimized for case overview breadth."""
    _events, result = consume_retrieval_generator(
        overview_retrieve_with_progress(
            db,
            understanding,
            workspace_id=workspace_id,
            document_ids=document_ids,
            query=query,
        )
    )
    return result
