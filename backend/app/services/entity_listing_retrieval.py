from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.config import settings
from app.schemas import SearchHit
from app.services.entity_index import lookup_pages_for_party_in_document
from app.services.listing_discovery import discover_listing_documents
from app.services.pass_retrieval import run_search_passes_for_document
from app.services.planned_retrieval import _fts_hit_to_search_hit
from app.services.query_understanding import QueryUnderstanding, SearchPass
from app.services.retrieval_progress import RetrievalProgressEmitter, consume_retrieval_generator


def _merge_pool(pool: dict, hits: list) -> None:
    for h in hits:
        existing = pool.get(h.chunk_id)
        if existing is None or h.score < existing.score:
            pool[h.chunk_id] = h


def _apply_doc_quotas(
    hits: list,
    *,
    min_per_doc: int,
    max_per_doc: int,
    limit: int,
    doc_order: list[str],
) -> list:
    by_doc: dict[str, list] = {}
    for h in hits:
        by_doc.setdefault(h.document_id, []).append(h)

    selected: list = []
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


def entity_listing_retrieve_with_progress(
    db: Session,
    understanding: QueryUnderstanding,
    *,
    workspace_id: str,
    document_ids: list[str] | None = None,
    query: str = "",
    tabular_review_id: str | None = None,
    emitter: RetrievalProgressEmitter | None = None,
) -> Iterator[dict]:
    """Entity-first retrieval: discover documents, then run planner passes per document."""
    progress = emitter or RetrievalProgressEmitter()
    target = understanding.target_entity
    canonicals = target.resolved_canonicals if target else []
    if not canonicals and understanding.constraints:
        for c in understanding.constraints:
            if c.type == "party":
                canonicals = [c.canonical]
                break

    yield progress.progress("search", "start", strategy="entity_matter_listing")

    doc_rows, discovery_diag = discover_listing_documents(
        db,
        understanding,
        workspace_id=workspace_id,
        document_ids=document_ids,
        query=query,
        tabular_review_id=tabular_review_id,
    )
    yield progress.progress(
        "search",
        "done",
        label="document_discovery",
        documents_discovered=len(doc_rows),
        target_entity=target.canonical if target else None,
        discovery_sources=discovery_diag.get("discovery_sources"),
    )

    document_ids_discovered = [d for d, _ in doc_rows]
    from app.services.listing_map_reduce import should_use_listing_map_reduce

    if should_use_listing_map_reduce(
        document_ids_discovered,
        tabular_review_id=tabular_review_id,
        db=db,
    ):
        diagnostics = {
            "retrieval_strategy": "entity_matter_listing",
            "target_entity": target.canonical if target else None,
            "resolved_canonicals": canonicals,
            "documents_discovered": len(doc_rows),
            "documents_total_discovered": discovery_diag.get(
                "documents_total_discovered", len(doc_rows),
            ),
            "document_ids_discovered": document_ids_discovered,
            "discovery_sources": discovery_diag.get("discovery_sources"),
            "pool_size": 0,
            "diverse_size": 0,
            "skipped_pool_for_map_reduce": True,
        }
        yield progress.progress("search", "done", pool_size=0, hit_count=0, strategy="listing_map_reduce")
        return [], diagnostics

    search_passes = list(understanding.search_passes)
    if not search_passes:
        terms = list(understanding.fts.must_terms[:2])
        if not terms and understanding.target_entity:
            terms = [
                t for t in understanding.target_entity.canonical.split()
                if len(t) > 2
            ][:2]
        if terms:
            search_passes = [
                SearchPass(label="entity_anchor", fts_terms=terms, operator="OR", pin_best=False)
            ]
    pool: dict = {}
    pages_per_doc: dict[str, list[int]] = {}
    per_doc_hits: dict[str, int] = {}

    chunks_per_doc = settings.chat_listing_chunks_per_doc
    min_per_doc = settings.chat_listing_min_chunks_per_doc
    pass_top_k = max(chunks_per_doc, 4)

    if not doc_rows and search_passes:
        yield progress.progress("search", "start", label="fallback_planned_passes")
        from app.services.fts_query_builder import build_fts_match_string
        from app.services.fts_search import fts_search
        from app.services.query_understanding import FtsPlan

        fallback: list = []
        for sp in search_passes:
            pass_plan = FtsPlan(must_terms=sp.fts_terms[:2], operator=sp.operator)
            pass_fts = build_fts_match_string(pass_plan, raw_query_fallback=" ".join(sp.fts_terms))
            hits = fts_search(
                db,
                query=query,
                fts_query=pass_fts,
                workspace_id=workspace_id,
                document_ids=document_ids,
                top_k=settings.chat_listing_pool_k,
                max_chunks_per_doc=chunks_per_doc,
            )
            fallback.extend(hits)
            _merge_pool(pool, hits)
        doc_rows = [(doc_id, 1) for doc_id in {h.document_id for h in fallback}]
        yield progress.progress("search", "done", label="fallback_planned_passes", hit_count=len(fallback))

    for doc_id, _mention_count in doc_rows:
        doc_name = progress.doc_names.get(doc_id, doc_id)
        yield progress.progress(
            "search",
            "start",
            label="per_document",
            document_id=doc_id,
            document_name=doc_name,
        )
        entity_pages = lookup_pages_for_party_in_document(
            db, workspace_id, doc_id, canonicals,
        )
        pages_per_doc[doc_id] = sorted(entity_pages)

        doc_hits = run_search_passes_for_document(
            db,
            workspace_id=workspace_id,
            document_id=doc_id,
            query=query,
            search_passes=search_passes,
            anchor_plan=understanding.fts,
            page_hint=entity_pages or None,
            pass_top_k=pass_top_k,
            max_chunks_per_doc=chunks_per_doc,
        )
        _merge_pool(pool, doc_hits)
        per_doc_hits[doc_id] = len(doc_hits)

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
            hit_count=per_doc_hits.get(doc_id, 0),
            pass_labels=[p.label for p in search_passes],
        )

    merged = sorted(pool.values(), key=lambda h: h.score)
    doc_order = [d for d, _ in doc_rows] if doc_rows else sorted({h.document_id for h in merged})
    diverse = _apply_doc_quotas(
        merged,
        min_per_doc=min_per_doc,
        max_per_doc=chunks_per_doc,
        limit=settings.chat_listing_pool_k,
        doc_order=doc_order,
    )

    rescue_note: str | None = None
    if not diverse:
        from app.services.query_understanding import FtsPlan, _case_name_terms

        case_terms = _case_name_terms(query)
        if case_terms:
            from app.services.fts_query_builder import build_fts_match_string
            from app.services.fts_search import fts_search

            plan = FtsPlan(must_terms=case_terms[:2], operator="AND")
            fts_q = build_fts_match_string(plan, raw_query_fallback=" ".join(case_terms))

            rescue_hits = fts_search(
                db,
                query=" ".join(case_terms),
                fts_query=fts_q,
                workspace_id=workspace_id,
                document_ids=document_ids,
                top_k=settings.chat_listing_pool_k,
                max_chunks_per_doc=chunks_per_doc,
            )
            diverse = [_fts_hit_to_search_hit(h) for h in rescue_hits]
            if diverse:
                rescue_note = "case_name_fts_fallback"

    diagnostics = {
        "retrieval_strategy": "entity_matter_listing",
        "target_entity": target.canonical if target else None,
        "resolved_canonicals": canonicals,
        "documents_discovered": len(doc_rows),
        "documents_total_discovered": discovery_diag.get(
            "documents_total_discovered", len(doc_rows),
        ),
        "document_ids_discovered": [d for d, _ in doc_rows],
        "discovery_sources": discovery_diag.get("discovery_sources"),
        "pages_per_doc": {k: v[:20] for k, v in pages_per_doc.items()},
        "per_doc_fts_hits": per_doc_hits,
        "pool_size": len(pool),
        "diverse_size": len(diverse),
        "search_pass_labels": [p.label for p in search_passes],
        "search_pass_count": len(search_passes),
    }
    if rescue_note:
        diagnostics["rescue"] = rescue_note
    yield progress.progress("search", "done", pool_size=len(pool), hit_count=len(diverse))
    return [_fts_hit_to_search_hit(h) for h in diverse], diagnostics


def entity_listing_retrieve(
    db: Session,
    understanding: QueryUnderstanding,
    *,
    workspace_id: str,
    document_ids: list[str] | None = None,
    query: str = "",
) -> tuple[list[SearchHit], dict]:
    """Entity-first retrieval: discover documents, then pool chunks per document."""
    _events, result = consume_retrieval_generator(
        entity_listing_retrieve_with_progress(
            db,
            understanding,
            workspace_id=workspace_id,
            document_ids=document_ids,
            query=query,
        )
    )
    return result
