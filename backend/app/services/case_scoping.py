from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.entity_index import lookup_documents_for_party_tokens
from app.services.fts_query_builder import build_fts_match_string
from app.services.fts_search import fts_search
from app.services.query_understanding import FtsPlan

_INVALID_CASE_PARTY_TOKENS = frozenset(
    {
        "summarize", "summarise", "summary", "passage", "passages", "discussing",
        "every", "across", "judgment", "mentioning", "plaintiff", "defendant",
        "informant", "context", "details", "detail", "case", "court", "facts",
    }
)


def _party_token_variants(term: str) -> list[str]:
    """Near-miss spellings for cited party tokens (e.g. ovens/owens)."""
    t = term.casefold()
    variants = [t]
    # Prioritize common v/w OCR confusions in case names before generic edits.
    for i, c in enumerate(t):
        if c == "v":
            swapped = t[:i] + "w" + t[i + 1:]
            if swapped not in variants:
                variants.insert(1, swapped)
        elif c == "w":
            swapped = t[:i] + "v" + t[i + 1:]
            if swapped not in variants:
                variants.insert(1, swapped)
    if len(t) < 4:
        return variants
    for i, c in enumerate(t):
        for alt in "aeiou":
            if alt == c:
                continue
            candidate = t[:i] + alt + t[i + 1:]
            if candidate not in variants:
                variants.append(candidate)
            if len(variants) >= 10:
                return variants
    return variants


def _fts_case_cooccurrence_hits(
    db: Session,
    *,
    workspace_id: str,
    case_terms: list[str],
    document_ids: list[str] | None,
) -> list:
    plan = FtsPlan(must_terms=case_terms[:2], operator="AND")
    fts_q = build_fts_match_string(plan, raw_query_fallback=" ".join(case_terms))
    return fts_search(
        db,
        query=" ".join(case_terms),
        fts_query=fts_q,
        workspace_id=workspace_id,
        document_ids=document_ids,
        top_k=40,
        max_chunks_per_doc=6,
    )


def _fuzzy_expand_case_terms(
    db: Session,
    workspace_id: str,
    case_terms: list[str],
    document_ids: list[str] | None,
) -> list[str] | None:
    """Resolve inverted or misspelled party tokens via entity index substring match."""
    if len(case_terms) < 2:
        return None
    doc_hits = lookup_documents_for_party_tokens(
        db,
        workspace_id,
        case_terms,
        document_ids,
        limit=4,
    )
    if not doc_hits:
        return None
    return [doc_hits[0][0]]


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

    hits = _fts_case_cooccurrence_hits(
        db, workspace_id=workspace_id, case_terms=case_terms, document_ids=document_ids,
    )
    if not hits:
        for variant in _party_token_variants(case_terms[0]):
            if variant == case_terms[0]:
                continue
            alt_terms = [variant, case_terms[1]]
            hits = _fts_case_cooccurrence_hits(
                db, workspace_id=workspace_id, case_terms=alt_terms, document_ids=document_ids,
            )
            if hits:
                break
    if not hits:
        fuzzy = _fuzzy_expand_case_terms(db, workspace_id, case_terms, document_ids)
        if fuzzy:
            return fuzzy
        reversed_terms = [case_terms[1], case_terms[0]]
        hits = _fts_case_cooccurrence_hits(
            db, workspace_id=workspace_id, case_terms=reversed_terms, document_ids=document_ids,
        )
        if not hits:
            return _fuzzy_expand_case_terms(db, workspace_id, reversed_terms, document_ids) or document_ids

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
