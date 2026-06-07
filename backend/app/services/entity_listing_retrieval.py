from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.config import settings
from app.schemas import SearchHit
from app.services.entity_page_context import (
    party_canonicals_from_understanding,
    retrieve_listing_page_hits,
)
from app.services.listing_discovery import discover_listing_documents
from app.services.planned_retrieval import _fts_hit_to_search_hit
from app.services.query_understanding import QueryUnderstanding, SearchPass
from app.services.retrieval_progress import RetrievalProgressEmitter, consume_retrieval_generator


def _merge_pool(pool: dict, hits: list) -> None:
    for h in hits:
        existing = pool.get(h.chunk_id)
        if existing is None or h.score < existing.score:
            pool[h.chunk_id] = h


def _party_match_tokens(understanding: QueryUnderstanding) -> list[str]:
    """Casefolded party name tokens (>=3 chars) from target + party constraints."""
    tokens: list[str] = []
    target = understanding.target_entity
    if target:
        tokens.extend(target.canonical.split())
        for s in target.surfaces:
            tokens.extend(s.split())
        for c in target.resolved_canonicals or []:
            tokens.extend(c.split())
    for c in understanding.constraints:
        if c.type == "party":
            tokens.extend(c.canonical.split())
            for s in c.surfaces:
                tokens.extend(s.split())
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        key = t.casefold().strip()
        if len(key) >= 3 and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _doc_hits_mention_target(hits: list, understanding: QueryUnderstanding) -> bool:
    """True if any hit's text contains a party token (case-insensitive).

    Returns True when there are no hits to evaluate or no party tokens known
    (caller pre-checks ``if doc_hits and not _doc_hits_mention_target(...)``).
    """
    if not hits:
        return True
    tokens = _party_match_tokens(understanding)
    if not tokens:
        return True
    for hit in hits:
        text = (getattr(hit, "text_content", "") or "").casefold()
        if not text:
            continue
        for token in tokens:
            if token in text:
                return True
    return False


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
    discovery_doc_limit: int | None = None,
    agent_deep: bool = False,
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
        discovery_doc_limit=discovery_doc_limit,
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
        document_ids=document_ids,
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

    party_canonicals = party_canonicals_from_understanding(understanding)
    if not party_canonicals:
        party_canonicals = canonicals

    pool: dict = {}
    pages_per_doc: dict[str, list[int]] = {}
    per_doc_hits: dict[str, int] = {}

    min_per_doc = settings.chat_listing_min_chunks_per_doc
    max_per_doc = settings.listing_max_pages_per_doc
    search_passes = list(understanding.search_passes)
    if not search_passes:
        terms = list(understanding.fts.must_terms[:2])
        if terms:
            search_passes = [
                SearchPass(label="entity_anchor", fts_terms=terms, operator="OR", pin_best=False)
            ]

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
                max_chunks_per_doc=max_per_doc,
            )
            fallback.extend(hits)
            _merge_pool(pool, [_fts_hit_to_search_hit(h) for h in hits])
        doc_rows = [(doc_id, 1) for doc_id in {h.document_id for h in fallback}]
        yield progress.progress("search", "done", label="fallback_planned_passes", hit_count=len(fallback))

    for doc_id, _mention_count in doc_rows:
        if len(pool) >= settings.chat_listing_pool_k:
            break
        doc_name = progress.doc_names.get(doc_id, doc_id)
        yield progress.progress(
            "search",
            "start",
            label="per_document",
            document_id=doc_id,
            document_name=doc_name,
        )
        yield progress.progress("page_rank", "start", document_id=doc_id, document_name=doc_name)
        doc_hits, page_diag = retrieve_listing_page_hits(
            db,
            workspace_id=workspace_id,
            document_id=doc_id,
            understanding=understanding,
            query=query,
            canonicals=party_canonicals,
            agent_deep=agent_deep,
        )
        pages_per_doc[doc_id] = page_diag.get("pages_selected") or []
        if doc_hits and not _doc_hits_mention_target(doc_hits, understanding):
            per_doc_hits[doc_id] = 0
            yield progress.progress(
                "page_rank",
                "done",
                document_id=doc_id,
                document_name=doc_name,
                pages_selected=pages_per_doc[doc_id],
            )
            yield progress.progress(
                "search",
                "done",
                label="per_document",
                document_id=doc_id,
                document_name=doc_name,
                hit_count=0,
                pages_selected=pages_per_doc[doc_id],
            )
            continue
        for h in doc_hits:
            _merge_pool(pool, [h])
        per_doc_hits[doc_id] = len(doc_hits)

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
            hit_count=per_doc_hits.get(doc_id, 0),
            pages_selected=pages_per_doc[doc_id],
        )

    merged = list(pool.values())
    doc_order = [d for d, _ in doc_rows] if doc_rows else sorted({h.document_id for h in merged})
    diverse = _apply_doc_quotas(
        merged,
        min_per_doc=min_per_doc,
        max_per_doc=max_per_doc,
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
                max_chunks_per_doc=max_per_doc,
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
    out_hits = [
        h if isinstance(h, SearchHit) else _fts_hit_to_search_hit(h)
        for h in diverse
    ]
    return out_hits, diagnostics


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
