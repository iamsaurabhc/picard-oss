from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.schemas import SearchHit
from app.services.entity_index import (
    lookup_documents_for_party,
    lookup_pages_for_party_in_document,
)
from app.services.fts_query_builder import build_fts_match_string
from app.services.fts_search import FtsHit, fts_search, fts_search_on_pages
from app.services.planned_retrieval import _early_page_thresholds, _fts_hit_to_search_hit
from app.services.query_understanding import FtsPlan, QueryUnderstanding


def _listing_anchor_fts(understanding: QueryUnderstanding, query: str) -> str:
    if understanding.target_entity and understanding.target_entity.surfaces:
        phrases = understanding.target_entity.surfaces[:1]
        plan = FtsPlan(phrases=phrases, must_terms=understanding.fts.must_terms[:2], operator="OR")
    else:
        plan = FtsPlan(
            must_terms=understanding.fts.must_terms[:2],
            phrases=understanding.fts.phrases,
            operator="OR",
        )
    return build_fts_match_string(plan, raw_query_fallback=query)


def _caption_pass_fts() -> str:
    return build_fts_match_string(
        FtsPlan(must_terms=["informant", "commission"], operator="AND"),
        raw_query_fallback="informant commission",
    )


def _merge_pool(pool: dict[str, FtsHit], hits: list[FtsHit]) -> None:
    for h in hits:
        existing = pool.get(h.chunk_id)
        if existing is None or h.score < existing.score:
            pool[h.chunk_id] = h


def _apply_doc_quotas(
    hits: list[FtsHit],
    *,
    min_per_doc: int,
    max_per_doc: int,
    limit: int,
    doc_order: list[str],
) -> list[FtsHit]:
    by_doc: dict[str, list[FtsHit]] = {}
    for h in hits:
        by_doc.setdefault(h.document_id, []).append(h)

    selected: list[FtsHit] = []
    seen: set[str] = set()

    for doc_id in doc_order:
        doc_hits = sorted(by_doc.get(doc_id, []), key=lambda x: x.score)
        for h in doc_hits[:min_per_doc]:
            if h.chunk_id not in seen:
                selected.append(h)
                seen.add(h.chunk_id)

    for doc_id in doc_order:
        doc_hits = sorted(by_doc.get(doc_id, []), key=lambda x: x.score)
        count = sum(1 for h in selected if h.document_id == doc_id)
        for h in doc_hits:
            if len(selected) >= limit:
                return selected
            if h.chunk_id in seen:
                continue
            if count >= max_per_doc:
                break
            selected.append(h)
            seen.add(h.chunk_id)
            count += 1

    for h in sorted(hits, key=lambda x: x.score):
        if len(selected) >= limit:
            break
        if h.chunk_id not in seen:
            selected.append(h)
            seen.add(h.chunk_id)

    return selected[:limit]


def entity_listing_retrieve(
    db: Session,
    understanding: QueryUnderstanding,
    *,
    workspace_id: str,
    document_ids: list[str] | None = None,
    query: str = "",
) -> tuple[list[SearchHit], dict]:
    """Entity-first retrieval: discover documents, then pool chunks per document."""
    target = understanding.target_entity
    canonicals = target.resolved_canonicals if target else []
    if not canonicals and understanding.constraints:
        for c in understanding.constraints:
            if c.type == "party":
                canonicals = [c.canonical]
                break

    max_docs = settings.chat_listing_max_docs
    doc_rows = lookup_documents_for_party(
        db,
        workspace_id,
        canonicals,
        document_ids,
        limit=max_docs,
    )

    anchor_fts = _listing_anchor_fts(understanding, query)
    caption_fts = _caption_pass_fts()
    pool: dict[str, FtsHit] = {}
    pages_per_doc: dict[str, list[int]] = {}
    per_doc_hits: dict[str, int] = {}

    chunks_per_doc = settings.chat_listing_chunks_per_doc
    min_per_doc = settings.chat_listing_min_chunks_per_doc

    if not doc_rows and anchor_fts:
        fallback = fts_search(
            db,
            query=query,
            fts_query=anchor_fts,
            workspace_id=workspace_id,
            document_ids=document_ids,
            top_k=settings.chat_listing_pool_k,
            max_chunks_per_doc=chunks_per_doc,
        )
        _merge_pool(pool, fallback)
        doc_rows = [
            (doc_id, 1)
            for doc_id in {h.document_id for h in fallback}
        ]

    early_thresholds = _early_page_thresholds(db, [d for d, _ in doc_rows] if doc_rows else document_ids)

    for doc_id, mention_count in doc_rows:
        entity_pages = lookup_pages_for_party_in_document(
            db, workspace_id, doc_id, canonicals,
        )
        pages_per_doc[doc_id] = sorted(entity_pages)

        page_set = {(doc_id, p) for p in entity_pages}
        if page_set and anchor_fts:
            hits = fts_search_on_pages(
                db,
                query=anchor_fts,
                workspace_id=workspace_id,
                pages=page_set,
                top_k=chunks_per_doc,
            )
            _merge_pool(pool, hits)
            per_doc_hits[doc_id] = len(hits)

        threshold = early_thresholds.get(doc_id, 3)
        early_pages = {(doc_id, p) for p in entity_pages if p <= threshold}
        if not early_pages:
            early_pages = {(doc_id, p) for p in range(1, min(threshold, 5) + 1)}
        if caption_fts and early_pages:
            caption_hits = fts_search_on_pages(
                db,
                query=caption_fts,
                workspace_id=workspace_id,
                pages=early_pages,
                top_k=2,
            )
            _merge_pool(pool, caption_hits)

    merged = sorted(pool.values(), key=lambda h: h.score)
    doc_order = [d for d, _ in doc_rows] if doc_rows else sorted({h.document_id for h in merged})
    diverse = _apply_doc_quotas(
        merged,
        min_per_doc=min_per_doc,
        max_per_doc=chunks_per_doc,
        limit=settings.chat_listing_pool_k,
        doc_order=doc_order,
    )

    diagnostics = {
        "retrieval_strategy": "entity_matter_listing",
        "target_entity": target.canonical if target else None,
        "resolved_canonicals": canonicals,
        "documents_discovered": len(doc_rows),
        "document_ids_discovered": [d for d, _ in doc_rows],
        "pages_per_doc": {k: v[:20] for k, v in pages_per_doc.items()},
        "per_doc_fts_hits": per_doc_hits,
        "pool_size": len(pool),
        "diverse_size": len(diverse),
        "anchor_fts": anchor_fts,
    }
    return [_fts_hit_to_search_hit(h) for h in diverse], diagnostics
