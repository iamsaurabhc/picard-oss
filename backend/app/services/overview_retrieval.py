from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.schemas import SearchHit
from app.services.planned_retrieval import PlannedRetrievalConfig, planned_retrieve
from app.services.query_understanding import QueryUnderstanding


def overview_retrieve(
    db: Session,
    understanding: QueryUnderstanding,
    *,
    workspace_id: str,
    document_ids: list[str] | None = None,
    query: str = "",
) -> tuple[list[SearchHit], dict]:
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
    hits, diagnostics = planned_retrieve(
        db,
        understanding,
        workspace_id=workspace_id,
        document_ids=document_ids,
        query=query,
        config=config,
    )
    return hits, diagnostics
