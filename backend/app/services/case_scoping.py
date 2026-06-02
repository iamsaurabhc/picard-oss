from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.fts_query_builder import build_fts_match_string
from app.services.fts_search import fts_search
from app.services.query_understanding import FtsPlan


def resolve_case_document_ids(
    db: Session,
    workspace_id: str,
    case_terms: list[str],
    document_ids: list[str] | None = None,
    *,
    limit: int = 2,
) -> list[str] | None:
    """Narrow workspace search to documents where case-name terms co-occur."""
    if len(case_terms) < 2:
        return document_ids
    if document_ids is not None and len(document_ids) <= 1:
        return document_ids

    plan = FtsPlan(must_terms=case_terms[:2], operator="AND")
    fts_q = build_fts_match_string(plan, raw_query_fallback=" ".join(case_terms))
    hits = fts_search(
        db,
        query=" ".join(case_terms),
        fts_query=fts_q,
        workspace_id=workspace_id,
        document_ids=document_ids,
        top_k=40,
        max_chunks_per_doc=6,
    )
    if not hits:
        return document_ids

    by_doc: dict[str, list] = {}
    for h in hits:
        by_doc.setdefault(h.document_id, []).append(h)

    scored = sorted(
        ((doc_id, len(doc_hits), min(h.score for h in doc_hits)) for doc_id, doc_hits in by_doc.items()),
        key=lambda row: (-row[1], row[2]),
    )
    if len(scored) == 1:
        return [scored[0][0]]
    top, second = scored[0], scored[1]
    if top[1] >= 2 and top[1] > second[1]:
        return [top[0]]
    return [doc_id for doc_id, _, _ in scored[:limit]]
