"""Entity-ranked full-page context for entity matter listing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Chunk, Document, Entity, PageEntity
from app.schemas import SearchHit
from app.services.carp import _load_page_chunks
from app.services.entity_index import (
    intersect_page_sets,
    lookup_pages_for_constraint,
    lookup_pages_for_party_in_document,
)
from app.services.excerpt_selector import _LISTING_CAPTION_RE
from app.services.fts_search import parse_bbox
from app.services.hybrid_search import enrich_fts_pool_with_hybrid
from app.services.pass_retrieval import run_search_passes_for_document
from app.services.planned_retrieval import _fts_hit_to_search_hit
from app.services.query_understanding import QueryUnderstanding, SearchPass

_LISTING_CAPTION_BOOST = 8.0
_CO_OCCURRENCE_BOOST = 25.0
_EARLY_PAGE_BOOST = 3.0


@dataclass
class ScoredPage:
    page_number: int
    score: float
    co_occurring: bool = False


def party_canonicals_from_understanding(understanding: QueryUnderstanding) -> list[str]:
    """All party canonicals for listing (target + constraints)."""
    canonicals: list[str] = []
    seen: set[str] = set()
    target = understanding.target_entity
    if target:
        for c in target.resolved_canonicals or [target.canonical]:
            key = c.casefold()
            if key not in seen:
                seen.add(key)
                canonicals.append(c)
    for constraint in understanding.constraints:
        if constraint.type != "party":
            continue
        key = constraint.canonical.casefold()
        if key not in seen:
            seen.add(key)
            canonicals.append(constraint.canonical)
    return canonicals


def _per_party_canonicals(canonicals: list[str]) -> list[list[str]]:
    if len(canonicals) <= 1:
        return [canonicals] if canonicals else []
    return [[c] for c in canonicals]


def _page_entity_mention_scores(
    db: Session,
    workspace_id: str,
    document_id: str,
    canonicals: list[str],
) -> dict[int, int]:
    if not canonicals:
        return {}
    stmt = (
        select(PageEntity.page_number, func.sum(PageEntity.mention_count))
        .join(Entity, Entity.id == PageEntity.entity_id)
        .where(
            Entity.workspace_id == workspace_id,
            Entity.entity_type == "party",
            Entity.canonical_value.in_(canonicals),
            PageEntity.document_id == document_id,
        )
        .group_by(PageEntity.page_number)
    )
    return {int(row[0]): int(row[1] or 0) for row in db.execute(stmt).all()}


def _load_page_chunks_cached(db: Session, document_id: str, page_number: int):
    from app.services.retrieval_context import get_retrieval_context

    key = (document_id, page_number)
    ctx = get_retrieval_context()
    if key in ctx.page_chunk_cache:
        return ctx.page_chunk_cache[key]
    chunks = _load_page_chunks(db, document_id, page_number)
    ctx.page_chunk_cache[key] = chunks
    return chunks


def _page_preview(db: Session, document_id: str, page_number: int, *, max_chars: int = 400) -> str:
    chunks = _load_page_chunks_cached(db, document_id, page_number)
    text = " ".join((c.text_content or "").strip() for c in chunks if c.text_content)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def _caption_boost(preview: str) -> float:
    return _LISTING_CAPTION_BOOST if _LISTING_CAPTION_RE.search(preview) else 0.0


def _fts_page_scores(
    db: Session,
    *,
    workspace_id: str,
    document_id: str,
    query: str,
    understanding: QueryUnderstanding,
    page_hint: set[int] | None,
) -> dict[int, float]:
    passes = list(understanding.search_passes)
    if not passes:
        terms = list(understanding.fts.must_terms[:2])
        if terms:
            passes = [
                SearchPass(label="entity_anchor", fts_terms=terms, operator="OR", pin_best=False)
            ]
    hits = run_search_passes_for_document(
        db,
        workspace_id=workspace_id,
        document_id=document_id,
        query=query,
        search_passes=passes,
        anchor_plan=understanding.fts,
        page_hint=page_hint,
        pass_top_k=settings.listing_max_pages_per_doc * 3,
        max_chunks_per_doc=settings.listing_max_pages_per_doc * 2,
    )
    pool: dict[str, object] = {h.chunk_id: h for h in hits}
    enrich_fts_pool_with_hybrid(
        db,
        pool,  # type: ignore[arg-type]
        query=query,
        workspace_id=workspace_id,
        document_ids=[document_id],
        pool_cap=settings.hybrid_pool_k,
    )
    by_page: dict[int, float] = {}
    for hit in pool.values():
        page = int(hit.page_number)
        bm25 = float(hit.score)
        rank_score = -bm25 if bm25 < 0 else 1.0 / (1.0 + bm25)
        by_page[page] = max(by_page.get(page, 0.0), rank_score)
    return by_page


def candidate_pages_for_document(
    db: Session,
    *,
    workspace_id: str,
    document_id: str,
    understanding: QueryUnderstanding,
    query: str,
    canonicals: list[str] | None = None,
) -> tuple[set[int], dict[int, float]]:
    """Union of entity-index, FTS/hybrid, and identifier pages for one document."""
    party_canonicals = canonicals or party_canonicals_from_understanding(understanding)
    pages: set[int] = set()

    if party_canonicals:
        pages |= lookup_pages_for_party_in_document(
            db, workspace_id, document_id, party_canonicals,
        )

    per_party = _per_party_canonicals(party_canonicals)
    if len(per_party) >= 2:
        page_sets = [
            {(document_id, p) for p in lookup_pages_for_party_in_document(
                db, workspace_id, document_id, group,
            )}
            for group in per_party
        ]
        co_pages = intersect_page_sets(page_sets)
        pages |= {p for _, p in co_pages}

    for constraint in understanding.constraints:
        if constraint.type == "identifier":
            id_pages = lookup_pages_for_constraint(
                db, workspace_id, "identifier", constraint.canonical, [document_id],
            )
            pages |= {p for _, p in id_pages}

    fts_scores = _fts_page_scores(
        db,
        workspace_id=workspace_id,
        document_id=document_id,
        query=query,
        understanding=understanding,
        page_hint=pages or None,
    )
    pages |= set(fts_scores.keys())

    if not pages:
        doc = db.get(Document, document_id)
        if doc and doc.page_count and doc.page_count <= 3:
            pages = set(range(1, int(doc.page_count) + 1))
    return pages, fts_scores


def _facet_entity_pages_for_document(
    db: Session,
    workspace_id: str,
    document_id: str,
    *,
    limit_per_type: int = 2,
) -> set[int]:
    """Top pages by indexed date, identifier, and amount entity density."""
    pages: set[int] = set()
    for entity_type in ("date", "identifier", "amount"):
        stmt = (
            select(PageEntity.page_number, func.sum(PageEntity.mention_count))
            .join(Entity, Entity.id == PageEntity.entity_id)
            .where(
                Entity.workspace_id == workspace_id,
                Entity.entity_type == entity_type,
                PageEntity.document_id == document_id,
            )
            .group_by(PageEntity.page_number)
            .order_by(func.sum(PageEntity.mention_count).desc())
            .limit(limit_per_type)
        )
        pages |= {int(row[0]) for row in db.execute(stmt).all()}
    return pages


def rank_pages_for_listing(
    db: Session,
    *,
    workspace_id: str,
    document_id: str,
    pages: set[int],
    query: str,
    understanding: QueryUnderstanding,
    canonicals: list[str] | None = None,
    agent_deep: bool = False,
    max_pages_per_doc: int | None = None,
    vector_page_scores_map: dict[int, float] | None = None,
    fts_by_page: dict[int, float] | None = None,
) -> list[ScoredPage]:
    """Score and order candidate pages; cap when document is large."""
    if not pages:
        return []

    party_canonicals = canonicals or party_canonicals_from_understanding(understanding)
    mention_scores = _page_entity_mention_scores(
        db, workspace_id, document_id, party_canonicals,
    )
    if fts_by_page is None:
        fts_by_page = _fts_page_scores(
            db,
            workspace_id=workspace_id,
            document_id=document_id,
            query=query,
            understanding=understanding,
            page_hint=pages,
        )

    co_occurring: set[int] = set()
    per_party = _per_party_canonicals(party_canonicals)
    if len(per_party) >= 2:
        page_sets = [
            {(document_id, p) for p in lookup_pages_for_party_in_document(
                db, workspace_id, document_id, group,
            )}
            for group in per_party
        ]
        co_occurring = {p for _, p in intersect_page_sets(page_sets)}

    doc = db.get(Document, document_id)
    page_count = int(doc.page_count or 0) if doc else 0
    if max_pages_per_doc is not None:
        max_pages = max_pages_per_doc
    elif agent_deep:
        max_pages = settings.agent_listing_max_pages_per_doc
    else:
        max_pages = settings.listing_max_pages_per_doc
    if page_count > settings.listing_large_doc_page_threshold:
        cap = max_pages
    else:
        cap = max(max_pages, len(pages))

    scored: list[ScoredPage] = []
    for page in pages:
        preview = _page_preview(db, document_id, page)
        score = float(mention_scores.get(page, 0))
        score += fts_by_page.get(page, 0.0) * 10.0
        score += _caption_boost(preview)
        if page in co_occurring:
            score += _CO_OCCURRENCE_BOOST
        if page <= 3:
            score += _EARLY_PAGE_BOOST
        if vector_page_scores_map and page in vector_page_scores_map:
            score += vector_page_scores_map[page] * 100.0
        scored.append(
            ScoredPage(page_number=page, score=score, co_occurring=page in co_occurring),
        )

    scored.sort(key=lambda s: (-s.score, s.page_number))
    return scored[:cap]


_OCR_NOISE_TOKEN_RE = re.compile(r"\b[A-Z0-9]{3,}[-/]?[A-Z0-9]{2,}\b")
_WORD_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


class _ChunkLike(Protocol):
    chunk_id: str
    text_content: str | None
    heading_path: str | None
    section_key: str | None
    bbox_json: str | None


def chunk_text_quality_score(text: str) -> float:
    """Higher = more likely substantive legal prose (not OCR header noise)."""
    t = (text or "").strip()
    if len(t) < 24:
        return -1e9
    alpha = sum(1 for c in t if c.isalpha())
    ratio = alpha / len(t)
    if ratio < 0.4:
        return -1e9
    noise = len(_OCR_NOISE_TOKEN_RE.findall(t))
    penalty = noise * 12.0
    if noise >= 3 and len(t) < 180:
        penalty += 80.0
    return len(t) * ratio - penalty


def best_representative_chunk(chunks: list[_ChunkLike]) -> _ChunkLike | None:
    """Pick the chunk whose bbox/text best matches what we show in page-level Sources."""
    if not chunks:
        return None
    return max(chunks, key=lambda c: chunk_text_quality_score(c.text_content or ""))


def token_overlap_score(needle: str, haystack: str) -> float:
    a = {t.casefold() for t in _WORD_TOKEN_RE.findall(needle or "") if len(t) > 2}
    if not a:
        return 0.0
    b = {t.casefold() for t in _WORD_TOKEN_RE.findall(haystack or "") if len(t) > 2}
    return len(a & b) / len(a)


def _best_chunk_for_sentence(sentence: str, page_chunks: list) -> tuple[object | None, float]:
    needle = (sentence or "").casefold().strip()
    if len(needle) < 8:
        return None, 0.0
    for length in (120, 80, 50, 30):
        fragment = needle[:length]
        if len(fragment) < 8:
            continue
        for chunk in page_chunks:
            text = (chunk.text_content or "").casefold()
            if fragment in text:
                return chunk, 1.0
    # Also try fragments from the middle/end of the sentence to avoid
    # false positives when sentences start with common legal boilerplate
    if len(needle) > 60:
        mid = len(needle) // 2
        for frag_start in (mid - 25, max(0, len(needle) - 50)):
            fragment = needle[frag_start:frag_start + 50]
            if len(fragment) < 20:
                continue
            for chunk in page_chunks:
                text = (chunk.text_content or "").casefold()
                if fragment in text:
                    return chunk, 0.95
    best_chunk = None
    best_score = 0.0
    for chunk in page_chunks:
        score = token_overlap_score(sentence, chunk.text_content or "")
        if score > best_score:
            best_score = score
            best_chunk = chunk
    if best_chunk is not None and best_score >= 0.35:
        return best_chunk, best_score
    return None, 0.0


def _chunk_read_order_key(chunk) -> tuple[float, str]:
    bbox = parse_bbox(chunk.bbox_json)
    if bbox and bbox.get("y0") is not None:
        return (float(bbox["y0"]), chunk.chunk_id)
    return (0.0, chunk.chunk_id)


def substantive_chunks_for_page(db: Session, document_id: str, page_number: int) -> list:
    """Load page chunks in reading order, keeping substantive text blocks only."""
    from app.services.entity_page_chunks import is_substantive_chunk_text

    page_chunks = _load_page_chunks_cached(db, document_id, page_number)
    substantive = [c for c in page_chunks if is_substantive_chunk_text(c.text_content or "")]
    return sorted(substantive, key=_chunk_read_order_key)


def chunk_for_id_on_page(
    db: Session,
    document_id: str,
    page_number: int,
    chunk_id: str,
):
    """Return the page chunk record for chunk_id, if present."""
    for chunk in _load_page_chunks_cached(db, document_id, page_number):
        if chunk.chunk_id == chunk_id:
            return chunk
    return None


def context_chunks_for_page(
    db: Session,
    document_id: str,
    page_number: int,
    context_chunk_ids: set[str],
    *,
    hit_text: str = "",
) -> list:
    """Substantive chunks limited to retrieval context, with text-overlap fallback."""
    from app.services.citation_binding import score_claim_to_chunk

    substantive = substantive_chunks_for_page(db, document_id, page_number)
    in_context = [c for c in substantive if c.chunk_id in context_chunk_ids]
    if in_context:
        return in_context
    if not substantive:
        return []
    if hit_text.strip():
        scored = sorted(
            substantive,
            key=lambda c: score_claim_to_chunk(hit_text[:400], c.text_content or ""),
            reverse=True,
        )
        return [scored[0]]
    return [substantive[0]]


def chunks_for_page_citation_refs(
    db: Session,
    document_id: str,
    page_number: int,
    context_chunk_ids: set[str],
    *,
    facet_excerpt: str = "",
) -> list:
    """Chunks for cite refs: retrieval hits plus chunks bound to facet excerpt sentences."""
    from app.services.citation_binding import ChunkCandidate, best_chunk_for_claim, score_claim_to_chunk
    from app.services.excerpt_selector import split_sentences

    substantive = substantive_chunks_for_page(db, document_id, page_number)
    if not substantive:
        return []
    selected_ids = set(context_chunk_ids)
    # Only fall back to top chunk if no retrieval hits exist on this page
    if substantive and not (selected_ids & {c.chunk_id for c in substantive}):
        top_chunk = min(substantive, key=_chunk_read_order_key)
        selected_ids.add(top_chunk.chunk_id)
    candidates = [
        ChunkCandidate(chunk_id=c.chunk_id, text=c.text_content or "")
        for c in substantive
    ]
    for sentence in split_sentences(facet_excerpt) if facet_excerpt else []:
        sent = sentence.strip()
        if len(sent) < 12:
            continue
        best, score = best_chunk_for_claim(sent, candidates, min_score=0.25)
        if best:
            selected_ids.add(best.chunk_id)
    ordered = [c for c in substantive if c.chunk_id in selected_ids]
    if ordered:
        return ordered
    if facet_excerpt.strip():
        scored = sorted(
            substantive,
            key=lambda c: score_claim_to_chunk(facet_excerpt[:400], c.text_content or ""),
            reverse=True,
        )
        return [scored[0]]
    return [substantive[0]]


def page_chunks_payload(db: Session, document_id: str, page_number: int) -> list[dict]:
    """All substantive chunks on a page for client-side claim anchoring."""
    return [
        {
            "chunk_id": c.chunk_id,
            "text": (c.text_content or "")[:800],
            "bbox": parse_bbox(c.bbox_json),
            "page": page_number,
        }
        for c in substantive_chunks_for_page(db, document_id, page_number)
    ]


def _merge_page_text(chunks: list, *, max_chars: int) -> str:
    parts = [(c.text_content or "").strip() for c in chunks if (c.text_content or "").strip()]
    merged = "\n\n".join(parts)
    if len(merged) <= max_chars:
        return merged
    return merged[:max_chars].rstrip() + "…"


def anchor_chunk_for_excerpt(
    db: Session,
    hit: SearchHit,
    excerpt: str,
) -> tuple[str, dict | None, list[dict], list[dict]]:
    """Pick chunk(s) whose text best contains excerpt sentences (fixes bbox/highlight alignment)."""
    from app.services.excerpt_selector import split_sentences

    page_chunks = _load_page_chunks_cached(db, hit.document_id, hit.page_number)
    if not page_chunks:
        return hit.chunk_id, hit.bbox, [], []

    sentences = split_sentences(excerpt) or ([excerpt.strip()] if excerpt and excerpt.strip() else [])
    sentence_anchors: list[dict] = []
    seen_chunk_ids: set[str] = set()
    highlight_bboxes: list[dict] = []
    best_primary: tuple[str, dict | None, float] | None = None

    for sentence in sentences:
        chunk, score = _best_chunk_for_sentence(sentence, page_chunks)
        if chunk is None or score <= 0:
            continue
        bbox = parse_bbox(chunk.bbox_json)
        sentence_anchors.append(
            {
                "sentence": sentence[:300],
                "chunk_id": chunk.chunk_id,
                "bbox": bbox,
                "score": round(score, 3),
            }
        )
        if chunk.chunk_id not in seen_chunk_ids and bbox:
            seen_chunk_ids.add(chunk.chunk_id)
            highlight_bboxes.append(bbox)
        if best_primary is None or score > best_primary[2]:
            best_primary = (chunk.chunk_id, bbox, score)

    if best_primary is not None:
        # Cap highlights to the 3 best-scoring anchors to avoid whole-page highlighting
        if len(highlight_bboxes) > 3:
            scored_anchors = sorted(
                [a for a in sentence_anchors if a.get("bbox")],
                key=lambda a: a.get("score", 0),
                reverse=True,
            )
            keep_ids: set[str] = set()
            kept_bboxes: list[dict] = []
            for a in scored_anchors:
                cid = a["chunk_id"]
                if cid not in keep_ids:
                    keep_ids.add(cid)
                    kept_bboxes.append(a["bbox"])
                if len(kept_bboxes) >= 3:
                    break
            highlight_bboxes = kept_bboxes
        return best_primary[0], best_primary[1], highlight_bboxes, sentence_anchors

    primary = best_representative_chunk(page_chunks) or page_chunks[0]
    bbox = parse_bbox(primary.bbox_json)
    return primary.chunk_id, bbox, [bbox] if bbox else [], []


def hits_from_ranked_pages(
    db: Session,
    document_id: str,
    ranked_pages: list[ScoredPage],
    *,
    max_chars_per_page: int | None = None,
) -> list[SearchHit]:
    """One SearchHit per page with merged chunk text (representative chunk_id for cites)."""
    cap = max_chars_per_page or settings.listing_max_chars_per_page
    hits: list[SearchHit] = []
    for sp in ranked_pages:
        page_chunks = _load_page_chunks_cached(db, document_id, sp.page_number)
        if not page_chunks:
            continue
        primary = best_representative_chunk(page_chunks) or page_chunks[0]
        text = _merge_page_text(page_chunks, max_chars=cap)
        hits.append(
            SearchHit(
                chunk_id=primary.chunk_id,
                document_id=document_id,
                page_number=sp.page_number,
                text_content=text,
                heading_path=primary.heading_path,
                section_key=primary.section_key,
                bbox=parse_bbox(primary.bbox_json),
                score=-sp.score,
            )
        )
    return hits


def retrieve_listing_page_hits(
    db: Session,
    *,
    workspace_id: str,
    document_id: str,
    understanding: QueryUnderstanding,
    query: str,
    canonicals: list[str] | None = None,
    agent_deep: bool = False,
    max_pages_per_doc: int | None = None,
) -> tuple[list[SearchHit], dict]:
    """Full pipeline: discover pages → rank → load page-level hits."""
    party_canonicals = canonicals or party_canonicals_from_understanding(understanding)
    candidates, fts_by_page = candidate_pages_for_document(
        db,
        workspace_id=workspace_id,
        document_id=document_id,
        understanding=understanding,
        query=query,
        canonicals=party_canonicals,
    )
    from app.services.hybrid_search import fuse_page_scores_rrf, vector_page_scores
    from app.services.latency_profile import resolve_latency_profile

    vector_scores: dict[int, float] = {}
    if not resolve_latency_profile().defer_page_vectors:
        vec_queries = [query] + [
            sq.question for sq in (understanding.sub_questions or [])
        ]
        if settings.chat_latency_profile.strip().lower() in {"balanced", "fast"}:
            vec_queries = vec_queries[:3]
        vector_scores = vector_page_scores(
            db,
            queries=vec_queries,
            workspace_id=workspace_id,
            document_ids=[document_id],
            top_k_per_query=settings.listing_max_pages_per_doc,
            fts_page_scores=fts_by_page,
        )
    fused_scores = (
        fuse_page_scores_rrf(
            {p: s * 10.0 for p, s in fts_by_page.items()},
            vector_scores,
        )
        if vector_scores
        else None
    )
    ranked = rank_pages_for_listing(
        db,
        workspace_id=workspace_id,
        document_id=document_id,
        pages=candidates,
        query=query,
        understanding=understanding,
        canonicals=party_canonicals,
        agent_deep=agent_deep,
        max_pages_per_doc=max_pages_per_doc,
        vector_page_scores_map=fused_scores,
        fts_by_page=fts_by_page,
    )
    hits = hits_from_ranked_pages(db, document_id, ranked)
    diag = {
        "candidate_pages": len(candidates),
        "pages_selected": [s.page_number for s in ranked],
        "co_occurring_pages": [s.page_number for s in ranked if s.co_occurring],
        "page_level": True,
    }
    return hits, diag


def retrieve_overview_page_hits(
    db: Session,
    *,
    workspace_id: str,
    document_id: str,
    query: str,
    understanding: QueryUnderstanding,
) -> tuple[list[SearchHit], dict]:
    """Case-overview: parallel entity + FTS + vector page discovery, full-page merge."""
    from app.services.hybrid_search import fuse_page_scores_rrf, vector_page_scores

    party_canonicals = party_canonicals_from_understanding(understanding)
    party_scoped = bool(party_canonicals)

    pages, fts_by_page = candidate_pages_for_document(
        db,
        workspace_id=workspace_id,
        document_id=document_id,
        understanding=understanding,
        query=query,
        canonicals=party_canonicals,
    )
    pages |= _facet_entity_pages_for_document(db, workspace_id, document_id)

    vec_queries = [query]
    for sq in understanding.sub_questions or []:
        vec_queries.append(sq.question)
    profile = settings.chat_latency_profile.strip().lower()
    if profile in {"balanced", "fast"}:
        vec_queries = vec_queries[:3]
    from app.services.latency_profile import resolve_latency_profile

    vector_scores: dict[int, float] = {}
    if not resolve_latency_profile(profile).defer_page_vectors:
        vector_scores = vector_page_scores(
            db,
            queries=vec_queries,
            workspace_id=workspace_id,
            document_ids=[document_id],
            top_k_per_query=6,
            fts_page_scores=fts_by_page,
        )
    pages |= set(vector_scores.keys())

    doc = db.get(Document, document_id)
    page_count = int(doc.page_count or 0) if doc else 0
    if page_count <= 12 and page_count > 0:
        pages |= set(range(1, page_count + 1))
    elif page_count > settings.listing_large_doc_page_threshold:
        pages |= set(range(1, 4))
    elif page_count > 0:
        pages |= set(range(1, min(4, page_count) + 1))
    if not pages:
        pages = {1}

    fused_page_scores = fuse_page_scores_rrf(
        {p: s * 10.0 for p, s in fts_by_page.items()},
        vector_scores,
    )

    max_pages = (
        settings.overview_party_scoped_max_pages
        if party_scoped
        else settings.overview_max_pages_per_doc
    )

    ranked = rank_pages_for_listing(
        db,
        workspace_id=workspace_id,
        document_id=document_id,
        pages=pages,
        query=query,
        understanding=understanding,
        canonicals=party_canonicals,
        max_pages_per_doc=max_pages,
        vector_page_scores_map=fused_page_scores,
        fts_by_page=fts_by_page,
    )
    hits = hits_from_ranked_pages(db, document_id, ranked)
    selected_pages = {h.page_number for h in hits}
    if len(selected_pages) < 3:
        for page in sorted(pages):
            if page in selected_pages:
                continue
            pad = hits_from_ranked_pages(db, document_id, [ScoredPage(page_number=page, score=0.0)])
            if not pad:
                continue
            hits.extend(pad)
            selected_pages.add(page)
            if len(selected_pages) >= 3:
                break
    extra = cross_page_reference_hits(
        db,
        workspace_id=workspace_id,
        document_id=document_id,
        understanding=understanding,
        query=query,
        seed_hits=hits,
    )
    if extra:
        seen = {h.page_number for h in hits}
        for h in extra:
            if h.page_number not in seen:
                hits.append(h)
                seen.add(h.page_number)
    diag = {
        "candidate_pages": len(pages),
        "pages_selected": [s.page_number for s in ranked],
        "page_level": True,
        "strategy": "overview_page_context",
        "party_scoped_pages": party_scoped,
        "vector_pages": sorted(vector_scores.keys()),
        "hybrid_fused_pages": len(fused_page_scores),
    }
    return hits, diag


def cross_page_reference_hits(
    db: Session,
    *,
    workspace_id: str,
    document_id: str,
    understanding: QueryUnderstanding,
    query: str,
    seed_hits: list[SearchHit],
    canonicals: list[str] | None = None,
) -> list[SearchHit]:
    """Optional FTS pass for pages referenced in seed text (large-doc stitching)."""
    if not seed_hits or settings.listing_cross_page_refs_max <= 0:
        return []
    case_nums = set(re.findall(r"\b(?:Case|Diary|Competition Appeal)\s+No\.?\s*[\w/.-]+", query, re.I))
    for hit in seed_hits[:3]:
        case_nums.update(
            re.findall(
                r"\b(?:Case|Diary|Competition Appeal)\s+No\.?\s*[\w/.-]+",
                hit.text_content or "",
                re.I,
            )
        )
    if not case_nums:
        return []
    extra_query = " OR ".join(sorted(case_nums)[:3])
    from app.services.fts_search import fts_search

    fts_hits = fts_search(
        db,
        query=extra_query,
        workspace_id=workspace_id,
        document_ids=[document_id],
        top_k=settings.listing_cross_page_refs_max * 2,
        max_chunks_per_doc=settings.listing_cross_page_refs_max,
    )
    existing_pages = {h.page_number for h in seed_hits}
    party_canonicals = canonicals or party_canonicals_from_understanding(understanding)
    out: list[SearchHit] = []
    for fh in fts_hits:
        if fh.page_number in existing_pages:
            continue
        page_chunks = _load_page_chunks_cached(db, document_id, fh.page_number)
        if not page_chunks:
            continue
        primary = page_chunks[0]
        text = _merge_page_text(
            page_chunks,
            max_chars=settings.listing_max_chars_per_page,
        )
        out.append(
            SearchHit(
                chunk_id=primary.chunk_id,
                document_id=document_id,
                page_number=fh.page_number,
                text_content=text,
                heading_path=primary.heading_path,
                section_key=primary.section_key,
                bbox=parse_bbox(primary.bbox_json),
                score=fh.score,
            )
        )
        if len(out) >= settings.listing_cross_page_refs_max:
            break
    return out
