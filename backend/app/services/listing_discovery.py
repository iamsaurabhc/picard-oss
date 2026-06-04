"""Unified document discovery for entity matter listing (entity index + FTS + optional tabular)."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from app.config import settings
from app.services.entity_index import (
    lookup_documents_for_party,
    lookup_documents_for_party_tokens,
)
from app.services.query_understanding import QueryUnderstanding, SearchPass


def _target_match_tokens(understanding: QueryUnderstanding) -> list[str]:
    tokens: list[str] = []
    target = understanding.target_entity
    if target:
        tokens.extend(t for t in target.canonical.split() if len(t) > 2)
        for s in target.surfaces:
            tokens.extend(t for t in s.split() if len(t) > 2)
    for c in understanding.constraints:
        if c.type == "party":
            tokens.extend(t for t in c.canonical.split() if len(t) > 2)
            for s in c.surfaces:
                tokens.extend(t for t in s.split() if len(t) > 2)
    tokens.extend(t for t in understanding.fts.must_terms if len(t) > 2)
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        key = t.casefold()
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out[:6]


def discover_documents_from_tabular(
    db: Session,
    review_id: str,
    *,
    match_tokens: list[str],
) -> list[tuple[str, int]]:
    """Score tabular review documents by party-column relevance to target tokens."""
    from app.services.tabular import discover_tabular_listing_documents

    return discover_tabular_listing_documents(db, review_id, match_tokens=match_tokens)


def discover_documents_from_party_fts(
    db: Session,
    *,
    workspace_id: str,
    document_ids: list[str] | None,
    query: str,
    understanding: QueryUnderstanding,
    match_tokens: list[str],
    limit: int | None = None,
) -> list[tuple[str, int]]:
    """Corpus-wide FTS document discovery with per-document aggregation (chat-first)."""
    from app.services.fts_query_builder import build_fts_match_string
    from app.services.fts_search import fts_discover_documents, _sanitize_fts_query
    from app.services.query_understanding import FtsPlan

    doc_limit = limit or settings.chat_listing_discovery_doc_limit
    per_doc: dict[str, int] = defaultdict(int)

    if match_tokens:
        or_terms = " OR ".join(match_tokens[:6])
        token_rows = fts_discover_documents(
            db,
            fts_query=or_terms,
            workspace_id=workspace_id,
            document_ids=document_ids,
            limit=doc_limit,
        )
        for doc_id, cnt in token_rows:
            per_doc[doc_id] = max(per_doc[doc_id], cnt)

    search_passes = list(understanding.search_passes)
    if not search_passes:
        terms = list(understanding.fts.must_terms[:2])
        if not terms and understanding.target_entity:
            terms = [
                t for t in understanding.target_entity.canonical.split() if len(t) > 2
            ][:2]
        if terms:
            search_passes = [
                SearchPass(label="entity_anchor", fts_terms=terms, operator="OR", pin_best=False)
            ]

    for sp in search_passes:
        if not sp.fts_terms:
            continue
        pass_plan = FtsPlan(must_terms=sp.fts_terms[:2], operator=sp.operator)
        pass_fts = build_fts_match_string(pass_plan, raw_query_fallback=" ".join(sp.fts_terms))
        if pass_fts:
            for doc_id, cnt in fts_discover_documents(
                db,
                fts_query=pass_fts,
                workspace_id=workspace_id,
                document_ids=document_ids,
                limit=doc_limit,
            ):
                per_doc[doc_id] = max(per_doc[doc_id], cnt)

    if query.strip() and len(per_doc) < doc_limit:
        raw_fts = _sanitize_fts_query(query)
        if raw_fts:
            for doc_id, cnt in fts_discover_documents(
                db,
                fts_query=raw_fts,
                workspace_id=workspace_id,
                document_ids=document_ids,
                limit=doc_limit,
            ):
                per_doc[doc_id] = max(per_doc[doc_id], cnt)

    return sorted(per_doc.items(), key=lambda x: -x[1])[:doc_limit]


def discover_documents_from_fts(
    db: Session,
    *,
    workspace_id: str,
    document_ids: list[str] | None,
    query: str,
    understanding: QueryUnderstanding,
) -> list[tuple[str, int]]:
    """Backward-compatible alias for party FTS document discovery."""
    return discover_documents_from_party_fts(
        db,
        workspace_id=workspace_id,
        document_ids=document_ids,
        query=query,
        understanding=understanding,
        match_tokens=_target_match_tokens(understanding),
    )


def discover_listing_documents(
    db: Session,
    understanding: QueryUnderstanding,
    *,
    workspace_id: str,
    document_ids: list[str] | None = None,
    query: str = "",
    tabular_review_id: str | None = None,
) -> tuple[list[tuple[str, int]], dict]:
    """
    Union entity index, party-token entity lookup, FTS doc facets, optional tabular.
    Returns (doc_rows ordered by prominence, discovery_sources diagnostics).
    """
    target = understanding.target_entity
    canonicals: list[str] = []
    if target and target.resolved_canonicals:
        canonicals = list(target.resolved_canonicals)
    elif target:
        canonicals = [target.canonical]
    if not canonicals and understanding.constraints:
        for c in understanding.constraints:
            if c.type == "party":
                canonicals = [c.canonical]
                break

    discovery_limit = settings.chat_listing_discovery_doc_limit
    match_tokens = _target_match_tokens(understanding)

    entity_rows = lookup_documents_for_party(
        db,
        workspace_id,
        canonicals,
        document_ids,
        limit=discovery_limit,
    )
    token_entity_rows = lookup_documents_for_party_tokens(
        db,
        workspace_id,
        match_tokens,
        document_ids,
        limit=discovery_limit,
    )

    fts_rows: list[tuple[str, int]] = []
    if settings.chat_listing_discovery_always_fts:
        fts_rows = discover_documents_from_party_fts(
            db,
            workspace_id=workspace_id,
            document_ids=document_ids,
            query=query,
            understanding=understanding,
            match_tokens=match_tokens,
            limit=discovery_limit,
        )

    tabular_rows: list[tuple[str, int]] = []
    if tabular_review_id:
        tabular_rows = discover_documents_from_tabular(
            db, tabular_review_id, match_tokens=match_tokens,
        )

    merged_scores: dict[str, int] = {}
    for doc_id, cnt in entity_rows:
        merged_scores[doc_id] = max(merged_scores.get(doc_id, 0), cnt)
    for doc_id, cnt in token_entity_rows:
        merged_scores[doc_id] = max(merged_scores.get(doc_id, 0), cnt)
    for doc_id, cnt in fts_rows:
        merged_scores[doc_id] = max(merged_scores.get(doc_id, 0), cnt)
    for doc_id, cnt in tabular_rows:
        merged_scores[doc_id] = max(merged_scores.get(doc_id, 0), cnt)

    token_entity_ids = {d for d, _ in token_entity_rows}
    tabular_ids = {d for d, _ in tabular_rows}
    entity_ids = {d for d, _ in entity_rows}
    fts_ids = {d for d, _ in fts_rows}

    if not merged_scores and tabular_review_id:
        from app.services.tabular import get_tabular_review_document_ids

        for doc_id in get_tabular_review_document_ids(db, tabular_review_id):
            merged_scores[doc_id] = 1

    doc_rows = sorted(merged_scores.items(), key=lambda x: -x[1])
    total_union = len(doc_rows)

    sources = {
        "entity": len(entity_ids),
        "entity_tokens": len(token_entity_ids),
        "tabular": len(tabular_ids),
        "fts": len(fts_ids),
        "union_total": total_union,
    }
    diagnostics = {
        "discovery_sources": sources,
        "documents_total_discovered": total_union,
    }
    return doc_rows, diagnostics
