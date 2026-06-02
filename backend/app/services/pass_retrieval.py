from __future__ import annotations

from app.schemas import SearchHit
from app.services.fts_query_builder import build_fts_match_string
from app.services.fts_search import FtsHit, fts_search, fts_search_on_pages
from app.services.planned_retrieval import _fts_hit_to_search_hit, _merge_hits
from app.services.query_understanding import FtsPlan, SearchPass


def run_search_passes_for_document(
    db,
    *,
    workspace_id: str,
    document_id: str,
    query: str,
    search_passes: list[SearchPass],
    anchor_plan: FtsPlan | None = None,
    page_hint: set[int] | None = None,
    pass_top_k: int = 4,
    max_chunks_per_doc: int = 4,
) -> list[FtsHit]:
    """Execute planner search passes scoped to one document (dynamic terms, no corpus rules)."""
    pool: dict[str, FtsHit] = {}

    if anchor_plan:
        anchor_fts = build_fts_match_string(anchor_plan, raw_query_fallback=query)
        if anchor_fts:
            if page_hint:
                pages = {(document_id, p) for p in page_hint}
                anchor_hits = fts_search_on_pages(
                    db,
                    query=anchor_fts,
                    workspace_id=workspace_id,
                    pages=pages,
                    top_k=pass_top_k,
                )
            else:
                anchor_hits = fts_search(
                    db,
                    query=query,
                    fts_query=anchor_fts,
                    workspace_id=workspace_id,
                    document_ids=[document_id],
                    top_k=pass_top_k,
                    max_chunks_per_doc=max_chunks_per_doc,
                )
            _merge_hits(pool, anchor_hits)

    for sp in search_passes:
        if not sp.fts_terms:
            continue
        pass_plan = FtsPlan(must_terms=sp.fts_terms[:2], operator=sp.operator)
        pass_fts = build_fts_match_string(pass_plan, raw_query_fallback=" ".join(sp.fts_terms))
        if not pass_fts:
            continue
        pass_hits = fts_search(
            db,
            query=query,
            fts_query=pass_fts,
            workspace_id=workspace_id,
            document_ids=[document_id],
            top_k=pass_top_k,
            max_chunks_per_doc=max_chunks_per_doc,
        )
        _merge_hits(pool, pass_hits)

    return sorted(pool.values(), key=lambda h: h.score)


def passes_to_search_hits(hits: list[FtsHit]) -> list[SearchHit]:
    return [_fts_hit_to_search_hit(h) for h in hits]
