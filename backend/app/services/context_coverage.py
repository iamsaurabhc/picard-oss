from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import settings
from app.schemas import ContextBundleOut, SearchHit
from app.services.carp import _load_page_chunks
from app.services.entity_index import lookup_pages_for_constraint
from app.services.excerpt_selector import has_amount_signal, has_identity_signal
from app.services.fts_query_builder import build_fts_match_string
from app.services.fts_search import fts_search, fts_search_on_pages, parse_bbox
from app.services.planned_retrieval import _fts_hit_to_search_hit, _valid_constraints
from app.services.query_understanding import (
    FtsPlan,
    QueryUnderstanding,
    SearchPass,
    SubQuestion,
    _passes_from_sub_questions,
)

_MAX_PAGE_CHUNKS_PER_SECTION = 6


@dataclass
class CoverageReport:
    sub_question_coverage: dict[str, str | None] = field(default_factory=dict)
    pass_labels_covered: dict[str, bool] = field(default_factory=dict)
    facets_covered: dict[str, bool] = field(default_factory=dict)
    gaps_filled: list[str] = field(default_factory=list)


def max_chunks_for_intent(intent: str, *, top_k: int) -> int:
    if intent == "entity_matter_listing":
        return min(settings.chat_listing_top_k, settings.context_expansion_max_chunks)
    if intent == "case_overview":
        return min(settings.chat_overview_top_k, settings.context_expansion_max_chunks)
    if intent == "factual_lookup":
        return min(max(top_k + 4, 14), settings.context_expansion_max_chunks)
    return min(top_k, settings.context_expansion_max_chunks)


def _hit_from_fts(hit) -> SearchHit:
    return _fts_hit_to_search_hit(hit)


def _merge_search_pool(pool: dict[str, SearchHit], fts_hits: list) -> None:
    for h in fts_hits:
        sh = _hit_from_fts(h)
        existing = pool.get(sh.chunk_id)
        if existing is None or sh.score < existing.score:
            pool[sh.chunk_id] = sh


def _page_key(hit: SearchHit) -> tuple[str, int]:
    return (hit.document_id, hit.page_number)


def _load_page_sibling_chunks(
    db: Session,
    document_id: str,
    page_number: int,
    *,
    cap: int = _MAX_PAGE_CHUNKS_PER_SECTION,
) -> list[SearchHit]:
    """All chunks on a page (co-location), capped."""
    page_hits = _load_page_chunks(db, document_id, page_number)
    return [_hit_from_fts(h) for h in page_hits[:cap]]


def _load_section_chunks(
    db: Session,
    document_id: str,
    page_number: int,
    section_key: str | None,
    *,
    cap: int = _MAX_PAGE_CHUNKS_PER_SECTION,
) -> list[SearchHit]:
    page_hits = _load_page_chunks(db, document_id, page_number)
    if section_key:
        filtered = [h for h in page_hits if h.section_key == section_key]
        pool = filtered if len(filtered) >= 2 else page_hits
    else:
        pool = page_hits
    return [_hit_from_fts(h) for h in pool[:cap]]


def expand_context_hits(
    db: Session,
    ranked_hits: list[SearchHit],
    *,
    bundles: list[ContextBundleOut] | None = None,
    max_chunks: int,
    max_per_page: int = 3,
) -> tuple[list[SearchHit], dict]:
    """Expand ranked hits with page/section siblings and CARP bundle chunks."""
    if not settings.enable_context_expansion or not ranked_hits:
        return ranked_hits, {"expanded": False, "expansion_added": 0}

    by_id: dict[str, SearchHit] = {h.chunk_id: h for h in ranked_hits}
    ranked_ids = [h.chunk_id for h in ranked_hits]
    expansion_added = 0

    seed_ids: list[str] = list(ranked_ids)
    if bundles:
        for bundle in bundles:
            seed_ids.extend(bundle.chunk_ids)

    for chunk_id in seed_ids:
        hit = by_id.get(chunk_id)
        if hit is None and bundles:
            for b in bundles:
                if chunk_id in b.chunk_ids:
                    break
            continue
        if hit is None:
            continue

        if settings.context_expansion_include_page_siblings:
            siblings = _load_page_sibling_chunks(
                db,
                hit.document_id,
                hit.page_number,
            )
            if hit.section_key:
                section_sibs = _load_section_chunks(
                    db,
                    hit.document_id,
                    hit.page_number,
                    hit.section_key,
                )
                seen_sib: set[str] = {s.chunk_id for s in siblings}
                for s in section_sibs:
                    if s.chunk_id not in seen_sib:
                        siblings.append(s)
                        seen_sib.add(s.chunk_id)
            page_count: dict[tuple[str, int], int] = {}
            for sib in siblings:
                key = _page_key(sib)
                if page_count.get(key, 0) >= max_per_page:
                    continue
                if sib.chunk_id in by_id:
                    continue
                by_id[sib.chunk_id] = sib
                expansion_added += 1
                page_count[key] = page_count.get(key, 0) + 1

    ordered: list[SearchHit] = []
    seen: set[str] = set()
    for cid in ranked_ids:
        if cid in by_id and cid not in seen:
            ordered.append(by_id[cid])
            seen.add(cid)
    extras = sorted(
        [h for cid, h in by_id.items() if cid not in seen],
        key=lambda x: (x.score, x.page_number),
    )
    for h in extras:
        if h.chunk_id not in seen:
            ordered.append(h)
            seen.add(h.chunk_id)

    if len(ordered) > max_chunks:
        ordered = ordered[:max_chunks]

    return ordered, {
        "expanded": True,
        "expansion_added": expansion_added,
        "context_chunk_count": len(ordered),
    }


def _pass_labels_with_hits(
    hits: list[SearchHit],
    passes: list[SearchPass],
) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for p in passes:
        terms = [t.casefold() for t in p.fts_terms if t]
        if not terms:
            continue
        result[p.label] = any(
            any(t in (h.text_content or "").casefold() for t in terms)
            for h in hits
        )
    return result


def _sub_question_satisfied(
    sq: SubQuestion,
    hits: list[SearchHit],
) -> str | None:
    label = sq.label.casefold()
    for h in hits:
        text = (h.text_content or "").casefold()
        if "name" in label or "identity" in label:
            if has_identity_signal(h.text_content):
                return h.chunk_id
        if "age" in label:
            if any(w in text for w in ("aged", "years", "year old", "infant")):
                return h.chunk_id
        if "date" in label or "accident" in label or "when" in label:
            months = (
                "january", "february", "march", "april", "may", "june",
                "july", "august", "september", "october", "november", "december",
            )
            if any(m in text for m in months) or any(c.isdigit() for c in text):
                return h.chunk_id
        if "amount" in label or "damage" in label:
            if has_amount_signal(h.text_content):
                return h.chunk_id
        terms = [t.casefold() for t in sq.fts_terms if t]
        if terms and any(t in text for t in terms):
            return h.chunk_id
    return None


def compute_coverage_report(
    hits: list[SearchHit],
    understanding: QueryUnderstanding,
    *,
    rank_diagnostics: dict | None = None,
) -> CoverageReport:
    report = CoverageReport()
    rank_diag = rank_diagnostics or {}

    sq_map = rank_diag.get("sub_question_coverage") or {}
    for sq in understanding.sub_questions:
        cid = sq_map.get(sq.label) if isinstance(sq_map, dict) else None
        if cid and any(h.chunk_id == cid for h in hits):
            report.sub_question_coverage[sq.label] = cid
        else:
            report.sub_question_coverage[sq.label] = _sub_question_satisfied(sq, hits)

    pass_hit = _pass_labels_with_hits(hits, understanding.search_passes)
    for label, covered in pass_hit.items():
        report.pass_labels_covered[label] = covered

    return report


def _gap_fill_passes(
    understanding: QueryUnderstanding,
    report: CoverageReport,
) -> list[SearchPass]:
    missing: list[SearchPass] = []
    for sq in understanding.sub_questions:
        if not report.sub_question_coverage.get(sq.label) and sq.fts_terms:
            missing.append(
                SearchPass(
                    label=f"gap_{sq.label}",
                    fts_terms=sq.fts_terms[:2],
                    operator=sq.operator,
                    pin_best=True,
                )
            )
    for label, covered in report.pass_labels_covered.items():
        if covered:
            continue
        orig = next((p for p in understanding.search_passes if p.label == label), None)
        if orig and orig.fts_terms:
            missing.append(
                SearchPass(
                    label=f"gap_{label}",
                    fts_terms=orig.fts_terms[:2],
                    operator=orig.operator,
                    pin_best=True,
                )
            )
    if not missing and understanding.sub_questions:
        missing = _passes_from_sub_questions(understanding.sub_questions)[:2]
    return missing[: settings.context_gap_fill_max_passes]


def gap_fill_retrieval(
    db: Session,
    *,
    query: str,
    understanding: QueryUnderstanding,
    workspace_id: str,
    document_ids: list[str] | None,
    pool: dict[str, SearchHit],
    report: CoverageReport,
) -> tuple[dict[str, SearchHit], list[str]]:
    """One bounded gap-fill round: targeted FTS passes for uncovered facets."""
    if not settings.query_planner_repair_on_zero_hits:
        return pool, []

    needs_fill = any(v is None for v in report.sub_question_coverage.values())
    needs_fill = needs_fill or any(not v for v in report.pass_labels_covered.values())
    if not needs_fill:
        return pool, []

    passes = _gap_fill_passes(understanding, report)
    if not passes:
        for c in _valid_constraints(understanding.constraints):
            pages = lookup_pages_for_constraint(
                db, workspace_id, c.type, c.canonical, document_ids,
            )
            if not pages:
                continue
            anchor = build_fts_match_string(understanding.fts, raw_query_fallback=query)
            entity_hits = fts_search_on_pages(
                db,
                query=anchor or query,
                workspace_id=workspace_id,
                pages=pages,
                top_k=6,
            )
            for h in entity_hits:
                sh = _hit_from_fts(h)
                pool[sh.chunk_id] = sh
            report.gaps_filled.append(f"entity_{c.type}")
        return pool, report.gaps_filled

    filled: list[str] = []
    for sp in passes:
        pass_plan = FtsPlan(must_terms=sp.fts_terms[:2], operator=sp.operator)
        pass_fts = build_fts_match_string(pass_plan, raw_query_fallback=" ".join(sp.fts_terms))
        pass_hits = fts_search(
            db,
            query=query,
            fts_query=pass_fts,
            workspace_id=workspace_id,
            document_ids=document_ids,
            top_k=6,
            max_chunks_per_doc=settings.chat_max_chunks_per_doc,
        )
        _merge_search_pool(pool, pass_hits)
        filled.append(sp.label)

    return pool, filled


def sandwich_order_hits(
    hits: list[SearchHit],
    *,
    sub_question_coverage: dict[str, str | None] | None = None,
) -> list[SearchHit]:
    """Place highest-signal chunks at start and end (lost-in-the-middle mitigation)."""
    if len(hits) <= 2:
        return hits

    by_id = {h.chunk_id: h for h in hits}
    priority_ids: list[str] = []
    if sub_question_coverage:
        for cid in sub_question_coverage.values():
            if cid and cid in by_id and cid not in priority_ids:
                priority_ids.append(cid)

    remaining = [h for h in hits if h.chunk_id not in priority_ids]
    if not remaining:
        return hits

    if len(remaining) == 1:
        return ([by_id[pid] for pid in priority_ids if pid in by_id] + remaining)[: len(hits)]

    first = remaining[0]
    second = remaining[1]
    middle = remaining[2:]
    ordered = [first, *middle, second]
    front = [by_id[pid] for pid in priority_ids if pid in by_id]
    seen = {h.chunk_id for h in front}
    out = front + [h for h in ordered if h.chunk_id not in seen]
    seen = {h.chunk_id for h in out}
    for h in hits:
        if h.chunk_id not in seen:
            out.append(h)
    return out[: len(hits)]


def apply_context_coverage(
    db: Session,
    ranked_hits: list[SearchHit],
    understanding: QueryUnderstanding,
    *,
    query: str,
    workspace_id: str,
    document_ids: list[str] | None,
    bundles: list[ContextBundleOut] | None = None,
    top_k: int,
    rank_diagnostics: dict | None = None,
) -> tuple[list[SearchHit], dict]:
    """Expand, gap-fill (once), re-verify coverage, and sandwich-order for synthesis."""
    max_chunks = max_chunks_for_intent(understanding.intent, top_k=top_k)
    max_per_page = (
        settings.chat_overview_max_chunks_per_page
        if understanding.intent == "case_overview"
        else 3
    )

    expanded, expand_diag = expand_context_hits(
        db,
        ranked_hits,
        bundles=bundles,
        max_chunks=max_chunks,
        max_per_page=max_per_page,
    )
    report = compute_coverage_report(expanded, understanding, rank_diagnostics=rank_diagnostics)

    pool = {h.chunk_id: h for h in expanded}
    pool, filled = gap_fill_retrieval(
        db,
        query=query,
        understanding=understanding,
        workspace_id=workspace_id,
        document_ids=document_ids,
        pool=pool,
        report=report,
    )
    if filled:
        merged = sorted(pool.values(), key=lambda h: h.score)
        expanded = expand_context_hits(
            db,
            merged[:max_chunks],
            bundles=bundles,
            max_chunks=max_chunks,
            max_per_page=max_per_page,
        )[0]
        report = compute_coverage_report(
            expanded, understanding, rank_diagnostics=rank_diagnostics
        )

    sq_cov = report.sub_question_coverage
    ordered = sandwich_order_hits(expanded, sub_question_coverage=sq_cov)

    diagnostics = {
        **expand_diag,
        "coverage_report": {
            "sub_question_coverage": report.sub_question_coverage,
            "pass_labels_covered": report.pass_labels_covered,
            "gaps_filled": report.gaps_filled,
        },
        "context_max_chunks": max_chunks,
        "sandwich_ordered": len(ordered) > 2,
    }
    return ordered, diagnostics
