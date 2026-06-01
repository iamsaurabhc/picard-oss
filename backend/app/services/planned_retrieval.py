from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Document, Entity, PageEntity
from app.schemas import SearchHit
from app.services.entity_index import lookup_pages_for_constraint
from app.services.fts_query_builder import build_fts_match_string
from app.services.fts_search import FtsHit, fts_search, fts_search_on_pages, parse_bbox
from app.services.query_understanding import FtsPlan, QueryUnderstanding, SearchPass
from app.services.retrieval_progress import RetrievalProgressEmitter, consume_retrieval_generator


@dataclass
class PlannedRetrievalConfig:
    pool_k: int
    max_per_page: int = 2
    min_distinct_pages: int = 1
    pin_best_default: bool = False
    anchor_top_k: int | None = None
    pass_top_k: int = 12
    entity_boost: bool = False
    early_page_bias: bool = False
    max_chunks_per_doc_multiplier: int = 3
    strategy: str = "planned"


def _fts_hit_to_search_hit(hit: FtsHit) -> SearchHit:
    return SearchHit(
        chunk_id=hit.chunk_id,
        document_id=hit.document_id,
        page_number=hit.page_number,
        text_content=hit.text_content,
        heading_path=hit.heading_path,
        section_key=hit.section_key,
        bbox=parse_bbox(hit.bbox_json),
        score=hit.score,
    )


def _merge_hits(pool: dict[str, FtsHit], hits: list[FtsHit]) -> None:
    for h in hits:
        existing = pool.get(h.chunk_id)
        if existing is None or h.score < existing.score:
            pool[h.chunk_id] = h


def _apply_page_diversity(
    hits: list[FtsHit],
    *,
    max_per_page: int,
    limit: int,
    pinned_ids: set[str] | None = None,
    min_distinct_pages: int = 1,
    early_page_thresholds: dict[str, int] | None = None,
) -> list[FtsHit]:
    pinned_ids = pinned_ids or set()
    early_page_thresholds = early_page_thresholds or {}
    pinned = [h for h in hits if h.chunk_id in pinned_ids]
    per_page: dict[tuple[str, int], int] = {}
    for h in pinned:
        per_page[(h.document_id, h.page_number)] = per_page.get((h.document_id, h.page_number), 0) + 1

    out: list[FtsHit] = list(pinned)
    seen = {h.chunk_id for h in pinned}
    covered_pages: set[tuple[str, int]] = {(h.document_id, h.page_number) for h in pinned}

    if early_page_thresholds:
        for doc_id, threshold in early_page_thresholds.items():
            if any(d == doc_id and p <= threshold for d, p in covered_pages):
                continue
            early = [
                h for h in sorted(hits, key=lambda x: x.score)
                if h.document_id == doc_id
                and h.page_number <= threshold
                and h.chunk_id not in seen
            ]
            if early:
                h = early[0]
                key = (h.document_id, h.page_number)
                if per_page.get(key, 0) < max_per_page:
                    out.append(h)
                    seen.add(h.chunk_id)
                    covered_pages.add(key)
                    per_page[key] = per_page.get(key, 0) + 1

    for h in sorted(hits, key=lambda x: x.score):
        if h.chunk_id in seen:
            continue
        key = (h.document_id, h.page_number)
        if per_page.get(key, 0) >= max_per_page:
            continue
        if len(covered_pages) < min_distinct_pages and key in covered_pages:
            continue
        per_page[key] = per_page.get(key, 0) + 1
        out.append(h)
        seen.add(h.chunk_id)
        covered_pages.add(key)
        if len(out) >= limit:
            break

    if len(out) < limit:
        for h in sorted(hits, key=lambda x: x.score):
            if h.chunk_id in seen:
                continue
            key = (h.document_id, h.page_number)
            if per_page.get(key, 0) >= max_per_page:
                continue
            per_page[key] = per_page.get(key, 0) + 1
            out.append(h)
            seen.add(h.chunk_id)
            if len(out) >= limit:
                break

    return out


def _early_page_thresholds(
    db: Session,
    document_ids: list[str] | None,
) -> dict[str, int]:
    if not document_ids:
        return {}
    docs = db.scalars(select(Document).where(Document.id.in_(document_ids))).all()
    thresholds: dict[str, int] = {}
    for doc in docs:
        if doc.page_count and doc.page_count > 0:
            thresholds[doc.id] = max(1, int(doc.page_count * 0.15))
        else:
            thresholds[doc.id] = 3
    return thresholds


def _top_entity_types_for_docs(
    db: Session,
    workspace_id: str,
    document_ids: list[str] | None,
    *,
    limit: int = 5,
) -> list[tuple[str, int]]:
    stmt = (
        select(Entity.entity_type, func.sum(PageEntity.mention_count).label("cnt"))
        .join(PageEntity, PageEntity.entity_id == Entity.id)
        .where(Entity.workspace_id == workspace_id)
        .group_by(Entity.entity_type)
        .order_by(func.sum(PageEntity.mention_count).desc())
        .limit(limit)
    )
    if document_ids:
        stmt = stmt.where(PageEntity.document_id.in_(document_ids))
    rows = db.execute(stmt).all()
    return [(r[0], int(r[1])) for r in rows]


def _entity_boost_passes(
    db: Session,
    workspace_id: str,
    document_ids: list[str] | None,
    existing_passes: list[SearchPass],
    query_terms: set[str],
) -> list[SearchPass]:
    existing_labels = {p.label for p in existing_passes}
    extra: list[SearchPass] = []
    for entity_type, _count in _top_entity_types_for_docs(db, workspace_id, document_ids):
        if entity_type in existing_labels:
            continue
        if entity_type in query_terms or entity_type.replace("_", " ") in " ".join(query_terms):
            terms = [entity_type.replace("_", " ")]
            if entity_type == "party":
                terms = ["plaintiff", "defendant"]
            elif entity_type == "amount":
                terms = ["damages", "sum"]
            extra.append(SearchPass(label=entity_type, fts_terms=terms, pin_best=True))
    return extra


def _valid_constraints(constraints) -> list:
    valid_types = {"party", "date", "condition", "identifier", "amount"}
    return [c for c in constraints if c.type in valid_types]


def _pass_labels_with_hits(
    pool: dict[str, FtsHit],
    search_passes: list[SearchPass],
) -> list[str]:
    labels: list[str] = []
    for sp in search_passes:
        terms = [t.casefold() for t in sp.fts_terms if t]
        if not terms:
            continue
        for h in pool.values():
            text = (h.text_content or "").casefold()
            if any(t in text for t in terms):
                labels.append(sp.label)
                break
    return labels


def planned_retrieve_with_progress(
    db: Session,
    understanding: QueryUnderstanding,
    *,
    workspace_id: str,
    document_ids: list[str] | None = None,
    query: str = "",
    config: PlannedRetrievalConfig,
    emitter: RetrievalProgressEmitter | None = None,
) -> Iterator[dict]:
    """Execute search_passes; yield progress/snippet events; return hits + diagnostics."""
    progress = emitter or RetrievalProgressEmitter()
    pool: dict[str, FtsHit] = {}
    pass_diag: list[str] = []
    pinned_ids: set[str] = set()

    yield progress.progress("search", "start", strategy=config.strategy)

    anchor_top_k = config.anchor_top_k or max(config.pool_k // 2, 8)
    anchor_plan = FtsPlan(
        must_terms=understanding.fts.must_terms[:2],
        phrases=understanding.fts.phrases,
        operator=understanding.fts.operator,
    )
    anchor_fts = build_fts_match_string(anchor_plan, raw_query_fallback=query)
    if anchor_fts or understanding.fts.must_terms or understanding.fts.phrases:
        yield progress.progress("search", "start", label="anchor")
        anchor_hits = fts_search(
            db,
            query=query,
            fts_query=anchor_fts,
            workspace_id=workspace_id,
            document_ids=document_ids,
            top_k=anchor_top_k,
            max_chunks_per_doc=config.max_per_page * config.max_chunks_per_doc_multiplier,
        )
        _merge_hits(pool, anchor_hits)
        pass_diag.append(f"anchor:{len(anchor_hits)}")
        best = progress.best_hit(anchor_hits)
        if best:
            snippet = progress.snippet_from_hit(best, "anchor")
            if snippet:
                yield snippet
        yield progress.progress("search", "done", label="anchor", hit_count=len(anchor_hits))

    search_passes = list(understanding.search_passes)
    query_terms = set(understanding.fts.must_terms)

    if config.entity_boost:
        search_passes.extend(
            _entity_boost_passes(db, workspace_id, document_ids, search_passes, query_terms)
        )

    for sp in search_passes:
        if not sp.fts_terms:
            continue
        yield progress.progress("search", "start", label=sp.label)
        pass_plan = FtsPlan(must_terms=sp.fts_terms[:2], operator=sp.operator)
        pass_fts = build_fts_match_string(pass_plan, raw_query_fallback=" ".join(sp.fts_terms))
        pass_hits = fts_search(
            db,
            query=query,
            fts_query=pass_fts,
            workspace_id=workspace_id,
            document_ids=document_ids,
            top_k=config.pass_top_k,
            max_chunks_per_doc=config.max_per_page * config.max_chunks_per_doc_multiplier,
        )
        pin_best = sp.pin_best if sp.pin_best is not None else config.pin_best_default
        if pass_hits and pin_best:
            best = min(pass_hits, key=lambda h: h.score)
            pool[best.chunk_id] = best
            pinned_ids.add(best.chunk_id)
        _merge_hits(pool, pass_hits)
        pass_diag.append(f"{sp.label}:{len(pass_hits)}")
        best = progress.best_hit(pass_hits)
        if best:
            snippet = progress.snippet_from_hit(best, sp.label)
            if snippet:
                yield snippet
        yield progress.progress("search", "done", label=sp.label, hit_count=len(pass_hits))

    for c in _valid_constraints(understanding.constraints):
        label = f"entity_{c.type}"
        pages = lookup_pages_for_constraint(
            db, workspace_id, c.type, c.canonical, document_ids,
        )
        if not pages:
            continue
        yield progress.progress("search", "start", label=label, constraint=c.canonical)
        entity_hits = fts_search_on_pages(
            db,
            query=anchor_fts or query,
            workspace_id=workspace_id,
            pages=pages,
            top_k=max(config.pool_k // 4, 4),
        )
        _merge_hits(pool, entity_hits)
        pass_diag.append(f"{label}:{len(entity_hits)}")
        best = progress.best_hit(entity_hits)
        if best:
            snippet = progress.snippet_from_hit(best, label)
            if snippet:
                yield snippet
        yield progress.progress("search", "done", label=label, hit_count=len(entity_hits))

    merged = sorted(pool.values(), key=lambda h: h.score)
    early_thresholds = _early_page_thresholds(db, document_ids) if config.early_page_bias else {}
    diverse = _apply_page_diversity(
        merged,
        max_per_page=config.max_per_page,
        limit=config.pool_k,
        pinned_ids=pinned_ids,
        min_distinct_pages=config.min_distinct_pages,
        early_page_thresholds=early_thresholds,
    )

    pages = {(h.document_id, h.page_number) for h in diverse}
    diagnostics = {
        "retrieval_strategy": config.strategy,
        "passes": pass_diag,
        "pool_size": len(pool),
        "diverse_size": len(diverse),
        "distinct_pages": len(pages),
        "anchor_fts": anchor_fts,
        "search_pass_labels": [p.label for p in understanding.search_passes],
        "pass_labels_hit": _pass_labels_with_hits(pool, understanding.search_passes),
    }
    if early_thresholds:
        diagnostics["early_page_thresholds"] = early_thresholds

    yield progress.progress("search", "done", pool_size=len(pool), hit_count=len(diverse))
    return [_fts_hit_to_search_hit(h) for h in diverse], diagnostics


def planned_retrieve(
    db: Session,
    understanding: QueryUnderstanding,
    *,
    workspace_id: str,
    document_ids: list[str] | None = None,
    query: str = "",
    config: PlannedRetrievalConfig,
) -> tuple[list[SearchHit], dict]:
    """Execute search_passes as independent FTS queries and merge into one pool."""
    _events, result = consume_retrieval_generator(
        planned_retrieve_with_progress(
            db,
            understanding,
            workspace_id=workspace_id,
            document_ids=document_ids,
            query=query,
            config=config,
        )
    )
    return result
