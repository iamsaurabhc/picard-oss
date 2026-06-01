from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import bindparam, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import MetadataTag
from app.services.constraint_planner import Constraint
from app.services.entity_index import (
    count_pages_for_constraint,
    intersect_page_sets,
    lookup_pages_for_constraint,
    lookup_section_pages_for_constraint,
    partial_overlap_diagnostics,
)
from app.services.fts_search import FtsHit, fts_search_on_pages, parse_bbox

ProximityTier = Literal["SAME_CHUNK", "SAME_PAGE", "SAME_SECTION", "ADJACENT_PAGE", "REFUSE"]

TIER_ORDER = ["SAME_PAGE", "SAME_SECTION", "ADJACENT_PAGE"]
TIER_SCORES = {
    "SAME_CHUNK": 1.0,
    "SAME_PAGE": 0.85,
    "SAME_SECTION": 0.65,
    "ADJACENT_PAGE": 0.40,
}


@dataclass
class ContextBundle:
    bundle_id: str
    document_id: str
    page_start: int
    page_end: int
    section_key: str | None
    heading_path: str | None
    chunk_ids: list[str]
    constraints_matched: list[str]
    constraints_missing: list[str]
    proximity_tier: ProximityTier
    bm25_score: float
    coherence_score: float
    score: float
    chunks: list[FtsHit] = field(default_factory=list)


@dataclass
class CarpResult:
    bundles: list[ContextBundle]
    chunks: list[FtsHit]
    refused: bool
    proximity_tier_used: ProximityTier | None
    retrieval_diagnostics: dict
    suggestions: list[str] = field(default_factory=list)


def _constraint_key(c: Constraint) -> str:
    return f"{c.type}:{c.canonical}"


def _max_tier_index(max_tier: str) -> int:
    try:
        return TIER_ORDER.index(max_tier)
    except ValueError:
        return len(TIER_ORDER) - 1


def _pages_same_section(
    db: Session,
    workspace_id: str,
    constraints: list[Constraint],
    document_ids: list[str] | None,
) -> set[tuple[str, int]]:
    section_sets: list[set[tuple[str, int]]] = []
    for c in constraints:
        mentions = lookup_section_pages_for_constraint(
            db, workspace_id, c.type, c.canonical, document_ids
        )
        by_section: dict[tuple[str, str | None], set[int]] = {}
        for doc_id, page, section in mentions:
            by_section.setdefault((doc_id, section), set()).add(page)
        pages: set[tuple[str, int]] = set()
        for (doc_id, section), pg_nums in by_section.items():
            if section is None:
                continue
            if len(pg_nums) >= 1:
                for pg in pg_nums:
                    pages.add((doc_id, pg))
        if pages:
            section_sets.append(pages)
    if len(section_sets) < len(constraints):
        return set()
    return intersect_page_sets(section_sets)


def _pages_adjacent(
    pages: set[tuple[str, int]],
) -> set[tuple[str, int]]:
    expanded: set[tuple[str, int]] = set()
    for doc_id, page in pages:
        expanded.add((doc_id, page))
        if page > 1:
            expanded.add((doc_id, page - 1))
        expanded.add((doc_id, page + 1))
    return expanded


def _intersect_at_tier(
    db: Session,
    workspace_id: str,
    constraints: list[Constraint],
    tier: str,
    document_ids: list[str] | None,
    prior_pages: set[tuple[str, int]] | None = None,
) -> set[tuple[str, int]]:
    page_sets = [
        lookup_pages_for_constraint(db, workspace_id, c.type, c.canonical, document_ids)
        for c in constraints
    ]
    if tier == "SAME_PAGE":
        return intersect_page_sets(page_sets)
    if tier == "SAME_SECTION":
        return _pages_same_section(db, workspace_id, constraints, document_ids)
    if tier == "ADJACENT_PAGE":
        base = prior_pages or intersect_page_sets(page_sets)
        if not base:
            return set()
        expanded = _pages_adjacent(base)
        for ps in page_sets:
            expanded &= _pages_adjacent(ps) if tier == "ADJACENT_PAGE" else ps
        return expanded
    return set()


def _load_page_chunks(
    db: Session,
    document_id: str,
    page_number: int,
) -> list[FtsHit]:
    from app.db.models import Chunk

    rows = db.scalars(
        select(Chunk)
        .where(Chunk.document_id == document_id, Chunk.page_number == page_number)
        .order_by(Chunk.id)
    ).all()
    return [
        FtsHit(
            chunk_id=c.id,
            document_id=c.document_id,
            page_number=c.page_number,
            text_content=c.text_content,
            heading_path=c.heading_path,
            section_key=c.section_key,
            bbox_json=c.bbox_json,
            score=0.0,
        )
        for c in rows
    ]


def _assemble_bundles(
    db: Session,
    *,
    workspace_id: str,
    query: str,
    pages: set[tuple[str, int]],
    constraints: list[Constraint],
    tier: ProximityTier,
    allow_partial: bool,
) -> list[ContextBundle]:
    bundles: list[ContextBundle] = []
    fts_hits = fts_search_on_pages(db, query=query, workspace_id=workspace_id, pages=pages)

    by_page_section: dict[tuple[str, int, str | None], list[FtsHit]] = {}
    if fts_hits:
        for hit in fts_hits:
            key = (hit.document_id, hit.page_number, hit.section_key)
            by_page_section.setdefault(key, []).append(hit)
    else:
        for doc_id, page in pages:
            for hit in _load_page_chunks(db, doc_id, page):
                key = (hit.document_id, hit.page_number, hit.section_key)
                by_page_section.setdefault(key, []).append(hit)

    for (doc_id, page, section_key), hits in by_page_section.items():
        page_constraint_keys: set[str] = set()
        for c in constraints:
            pages_for_c = lookup_pages_for_constraint(db, workspace_id, c.type, c.canonical, [doc_id])
            if (doc_id, page) in pages_for_c:
                page_constraint_keys.add(_constraint_key(c))
            elif tier == "SAME_SECTION" and section_key:
                section_mentions = lookup_section_pages_for_constraint(
                    db, workspace_id, c.type, c.canonical, [doc_id]
                )
                if any(d == doc_id and s == section_key for d, _, s in section_mentions):
                    page_constraint_keys.add(_constraint_key(c))

        matched = sorted(page_constraint_keys)
        missing = sorted({_constraint_key(c) for c in constraints} - page_constraint_keys)
        if not matched:
            continue
        if missing and not allow_partial:
            continue

        bm25 = min(h.score for h in hits) if hits else 0.0
        coherence = 1.0 if section_key else 0.5
        w1, w2, w3, w4 = 0.35, 0.25, 0.25, 0.15
        score = (
            w1 * (len(matched) / max(len(constraints), 1))
            + w2 * TIER_SCORES.get(tier, 0.5)
            + w3 * min(-bm25 / 20.0, 1.0)
            + w4 * coherence
        )
        heading = hits[0].heading_path if hits else None
        bundles.append(
            ContextBundle(
                bundle_id=str(uuid.uuid4()),
                document_id=doc_id,
                page_start=page,
                page_end=page,
                section_key=section_key,
                heading_path=heading,
                chunk_ids=[h.chunk_id for h in hits],
                constraints_matched=matched,
                constraints_missing=missing,
                proximity_tier=tier,
                bm25_score=bm25,
                coherence_score=coherence,
                score=score,
                chunks=hits,
            )
        )
    bundles.sort(key=lambda b: b.score, reverse=True)
    return bundles[: settings.carp_top_k_bundles]


def run_carp(
    db: Session,
    *,
    query: str,
    workspace_id: str,
    constraints: list[Constraint],
    document_ids: list[str] | None = None,
    proximity_max_tier: str | None = None,
    allow_partial_disclosure: bool | None = None,
) -> CarpResult:
    max_tier = proximity_max_tier or settings.carp_max_proximity_tier
    allow_partial = (
        settings.carp_allow_partial_disclosure
        if allow_partial_disclosure is None
        else allow_partial_disclosure
    )
    max_idx = _max_tier_index(max_tier)

    diagnostics = partial_overlap_diagnostics(db, workspace_id, constraints, document_ids)
    diagnostics["intersection_pages"] = 0

    suggestions: list[str] = []
    tier_used: ProximityTier | None = None
    candidate_pages: set[tuple[str, int]] = set()

    for i, tier in enumerate(TIER_ORDER):
        if i > max_idx:
            break
        pages = _intersect_at_tier(db, workspace_id, constraints, tier, document_ids)
        if pages:
            candidate_pages = pages
            tier_used = tier  # type: ignore[assignment]
            diagnostics["intersection_pages"] = len(pages)
            break

    if not candidate_pages and allow_partial:
        page_sets = [
            lookup_pages_for_constraint(db, workspace_id, c.type, c.canonical, document_ids)
            for c in constraints
        ]
        for ps in page_sets:
            candidate_pages |= ps
        if candidate_pages:
            tier_used = "ADJACENT_PAGE"
            suggestions.append("Partial disclosure: constraints may not co-occur on the same page.")

    if not candidate_pages:
        suggestions.extend([
            "Try adjacent-page proximity (widens to ±1 page).",
            "Confirm entity spellings match indexed canonical values.",
            "Condition may appear only in section headings — check heading_path index.",
        ])
        return CarpResult(
            bundles=[],
            chunks=[],
            refused=True,
            proximity_tier_used=None,
            retrieval_diagnostics=diagnostics,
            suggestions=suggestions,
        )

    bundles = _assemble_bundles(
        db,
        workspace_id=workspace_id,
        query=query,
        pages=candidate_pages,
        constraints=constraints,
        tier=tier_used or "SAME_PAGE",
        allow_partial=allow_partial,
    )

    if not bundles and not allow_partial:
        return CarpResult(
            bundles=[],
            chunks=[],
            refused=True,
            proximity_tier_used=tier_used,
            retrieval_diagnostics=diagnostics,
            suggestions=["No bundles matched all constraints at current proximity tier."],
        )

    flat_chunks: list[FtsHit] = []
    seen: set[str] = set()
    for bundle in bundles:
        for hit in bundle.chunks:
            if hit.chunk_id not in seen:
                seen.add(hit.chunk_id)
                flat_chunks.append(hit)

    return CarpResult(
        bundles=bundles,
        chunks=flat_chunks,
        refused=False,
        proximity_tier_used=tier_used,
        retrieval_diagnostics=diagnostics,
        suggestions=suggestions,
    )


def filter_documents_by_metadata(
    db: Session,
    workspace_id: str,
    metadata_filters: dict[str, str] | None,
    document_ids: list[str] | None = None,
) -> list[str] | None:
    if not metadata_filters:
        return document_ids

    from app.db.models import Document

    doc_ids: set[str] | None = set(document_ids) if document_ids else None
    for key, value in metadata_filters.items():
        rows = db.scalars(
            select(MetadataTag.document_id)
            .join(Document, Document.id == MetadataTag.document_id)
            .where(
                Document.workspace_id == workspace_id,
                MetadataTag.tag_key == key,
                MetadataTag.tag_value == value,
            )
        ).all()
        matching = set(rows)
        if doc_ids is None:
            doc_ids = matching
        else:
            doc_ids &= matching
    return list(doc_ids) if doc_ids is not None else []
