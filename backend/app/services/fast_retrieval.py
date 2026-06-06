"""Fast-tier retrieval for early synthesis (rule-only, anchor FTS, heuristic rank)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.schemas import SearchHit
from app.services.citation_kernel import build_evidence_prompt_and_map
from app.services.citations import CitationMap
from app.services.fts_query_builder import build_fts_match_string
from app.services.fts_search import fts_search, parse_bbox
from app.services.query_understanding import FtsPlan, QueryUnderstanding, understand_query


def fast_retrieve_for_chat(
    db: Session,
    *,
    query: str,
    understanding: QueryUnderstanding | None,
    workspace_id: str,
    document_ids: list[str] | None,
) -> tuple[list[SearchHit], CitationMap | None, str | None, dict]:
    """
    Minimal retrieval path targeting <3s: rule understanding (if needed),
    single anchor FTS, heuristic excerpts via build_evidence_prompt_and_map.
    """
    u = understanding or understand_query(
        query,
        retrieval_mode="simple",
        db=db,
        workspace_id=workspace_id,
        document_ids=document_ids,
    )
    fts_query = build_fts_match_string(u.fts, raw_query_fallback=query)
    if not fts_query and u.search_passes:
        sp = u.search_passes[0]
        fts_query = build_fts_match_string(
            FtsPlan(must_terms=[], should_terms=sp.fts_terms, operator=sp.operator),
            raw_query_fallback=query,
        )
    hits_raw = fts_search(
        db,
        query=query,
        fts_query=fts_query or query,
        workspace_id=workspace_id,
        document_ids=document_ids,
        top_k=min(settings.chat_top_k, 8),
        max_chunks_per_doc=settings.chat_max_chunks_per_doc,
    )
    hits = [
        SearchHit(
            chunk_id=h.chunk_id,
            document_id=h.document_id,
            page_number=h.page_number,
            text_content=h.text_content,
            heading_path=h.heading_path,
            section_key=h.section_key,
            bbox=parse_bbox(h.bbox_json),
            score=h.score,
        )
        for h in hits_raw
    ]
    if not hits:
        return [], None, None, {"fast_tier": True, "hit_count": 0}

    from app.services.chat import get_document_names

    doc_names = get_document_names(db, list({h.document_id for h in hits}))
    citation_map, system_prompt = build_evidence_prompt_and_map(
        db,
        hits=hits,
        query=query,
        understanding=u,
        bundles=None,
        doc_names=doc_names,
        workspace_id=workspace_id,
        is_listing=False,
        is_overview=u.intent == "case_overview",
    )
    return hits, citation_map, system_prompt, {"fast_tier": True, "hit_count": len(hits)}
