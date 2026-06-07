from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.config import settings
from app.schemas import SearchHit
from app.services.case_scoping import resolve_case_document_ids
from app.services.entity_page_context import retrieve_overview_page_hits
from app.services.planned_retrieval import (
    PlannedRetrievalConfig,
    planned_retrieve_with_progress,
)
from app.services.query_understanding import (
    QueryUnderstanding,
    _case_name_terms,
    _is_singular_case_details_query,
)
from app.services.retrieval_progress import RetrievalProgressEmitter


def _discover_overview_documents(
    db: Session,
    understanding: QueryUnderstanding,
    *,
    workspace_id: str,
    document_ids: list[str] | None,
    query: str,
) -> tuple[list[str], dict]:
    """Party/informant-scoped overview: discover documents via entity index + FTS."""
    from app.services.listing_discovery import discover_listing_documents

    doc_rows, diag = discover_listing_documents(
        db,
        understanding,
        workspace_id=workspace_id,
        document_ids=document_ids,
        query=query,
    )
    if not doc_rows:
        return [], diag
    limit = (
        1
        if _is_singular_case_details_query(query)
        else settings.overview_page_context_max_docs
    )
    selected = [doc_id for doc_id, _ in doc_rows[:limit]]
    diag["doc_rows_preview"] = doc_rows[:5]
    return selected, diag


def overview_retrieve_with_progress(
    db: Session,
    understanding: QueryUnderstanding,
    *,
    workspace_id: str,
    document_ids: list[str] | None = None,
    query: str = "",
    emitter: RetrievalProgressEmitter | None = None,
) -> Iterator[dict]:
    """Multi-pass or page-level retrieval optimized for case overview breadth."""
    progress = emitter or RetrievalProgressEmitter()
    case_terms = _case_name_terms(query) or list(understanding.fts.must_terms[:2])
    discovery_diag: dict = {}
    party_scoped = (
        not _case_name_terms(query)
        and (
            understanding.target_entity is not None
            or any(c.type == "party" for c in understanding.constraints)
        )
    )
    if party_scoped:
        discovered, discovery_diag = _discover_overview_documents(
            db,
            understanding,
            workspace_id=workspace_id,
            document_ids=document_ids,
            query=query,
        )
        if document_ids and not discovered:
            discovered, discovery_diag = _discover_overview_documents(
                db,
                understanding,
                workspace_id=workspace_id,
                document_ids=None,
                query=query,
            )
            discovery_diag["widened_to_workspace"] = True
        target_docs = discovered
    else:
        scoped_ids = resolve_case_document_ids(
            db,
            workspace_id,
            case_terms,
            document_ids,
        )
        target_docs = list(scoped_ids or document_ids or [])

    if (
        target_docs
        and len(target_docs) <= settings.overview_page_context_max_docs
    ):
        yield progress.progress(
            "search",
            "start",
            strategy="overview_page_context",
            documents_to_search=len(target_docs),
        )
        pool: dict[str, SearchHit] = {}
        pages_per_doc: dict[str, list[int]] = {}
        for doc_id in target_docs:
            doc_name = progress.doc_names.get(doc_id, doc_id)
            yield progress.progress(
                "search",
                "start",
                label="per_document",
                document_id=doc_id,
                document_name=doc_name,
            )
            yield progress.progress("page_rank", "start", document_id=doc_id, document_name=doc_name)
            doc_hits, page_diag = retrieve_overview_page_hits(
                db,
                workspace_id=workspace_id,
                document_id=doc_id,
                query=query,
                understanding=understanding,
            )
            pages_per_doc[doc_id] = page_diag.get("pages_selected") or []
            for h in doc_hits:
                pool[h.chunk_id] = h
            yield progress.progress(
                "page_rank",
                "done",
                document_id=doc_id,
                document_name=doc_name,
                pages_selected=pages_per_doc[doc_id],
            )
            best = progress.best_hit(doc_hits)
            if best:
                snippet = progress.snippet_from_hit(best, f"doc:{doc_name}")
                if snippet:
                    yield snippet
            yield progress.progress(
                "search",
                "done",
                label="per_document",
                document_id=doc_id,
                document_name=doc_name,
                hit_count=len(doc_hits),
                pages_selected=pages_per_doc[doc_id],
            )
        hits = sorted(pool.values(), key=lambda h: h.score)
        distinct_pages = len({h.page_number for h in hits})
        diagnostics = {
            "retrieval_strategy": "case_overview",
            "strategy": "overview_page_context",
            "pages_per_doc": pages_per_doc,
            "pool_size": len(hits),
            "distinct_pages": distinct_pages,
            "scoped_document_ids": target_docs,
            "party_scoped_discovery": party_scoped,
            **({"discovery": discovery_diag} if discovery_diag else {}),
        }
        yield progress.progress("search", "done", hit_count=len(hits), strategy="overview_page_context")
        return hits, diagnostics

    config = PlannedRetrievalConfig(
        pool_k=settings.chat_overview_pool_k,
        max_per_page=settings.chat_overview_max_chunks_per_page,
        min_distinct_pages=3,
        pin_best_default=True,
        anchor_top_k=settings.chat_overview_pool_k // 2,
        pass_top_k=max(settings.chat_overview_pool_k // 3, 12),
        entity_boost=True,
        early_page_bias=True,
        strategy="case_overview",
    )
    planned_doc_ids = target_docs if target_docs else (document_ids)
    return (yield from planned_retrieve_with_progress(
        db,
        understanding,
        workspace_id=workspace_id,
        document_ids=planned_doc_ids,
        query=query,
        config=config,
        emitter=progress,
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
    from app.services.retrieval_progress import consume_retrieval_generator

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
