from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import settings
from app.schemas import ContextBundleOut, SearchHit
from app.services.carp import _load_page_chunks
from app.services.entity_index import lookup_pages_for_constraint
from app.services.excerpt_selector import has_explicit_monetary_amount, has_identity_signal
from app.services.fts_query_builder import build_fts_match_string
from app.services.fts_search import fts_search, fts_search_on_pages
from app.services.planned_retrieval import _fts_hit_to_search_hit, _valid_constraints
from app.services.query_understanding import (
    FtsPlan,
    QueryUnderstanding,
    SearchPass,
    SubQuestion,
    _passes_from_sub_questions,
)

_MAX_PAGE_CHUNKS_PER_SECTION = 6

_MONTHS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)
_CITATION_NOISE_RE = re.compile(
    r"\b(?:78FCR|SASR|\d+[A-Z]{2,}\d+)\b|\[\d+\]\s*\d+[A-Z]{2,}",
    re.IGNORECASE,
)
_CALENDAR_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|"
    r"January|February|March|April|May|June|July|August|September|October|November|December"
    r"\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)
_DATE_PROCEDURE_RE = re.compile(
    r"\b(?:filed|entered|heard|decided|issued|granted|served|commenced|lodged)\b",
    re.IGNORECASE,
)
_PARTY_ROLE_RE = re.compile(
    r"\b(?:plaintiff|defendant|claimant|respondent|appellant|informant|applicant)\b",
    re.IGNORECASE,
)
_PROPER_NAME_IN_TEXT_RE = re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]+)?\b")
_COURT_FORUM_RE = re.compile(
    r"\b(?:court|commission|tribunal|chancery|division|council)\b",
    re.IGNORECASE,
)
_CASE_ID_RE = re.compile(r"\b(?:no\.?|number|diary|citation)\s*[\dA-Z/\-]+", re.IGNORECASE)


@dataclass
class CoverageReport:
    sub_question_coverage: dict[str, str | None] = field(default_factory=dict)
    pass_labels_covered: dict[str, bool] = field(default_factory=dict)
    facets_covered: dict[str, bool] = field(default_factory=dict)
    facets_weak: dict[str, bool] = field(default_factory=dict)
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


def _strict_date_signal(text: str | None, *, require_strict: bool = False) -> bool:
    if not text:
        return False
    t = text.strip()
    if _CITATION_NOISE_RE.search(t) and not _CALENDAR_DATE_RE.search(t):
        return False
    if any(m in t.casefold() for m in _MONTHS):
        return True
    if _CALENDAR_DATE_RE.search(t):
        return True
    if require_strict:
        return bool(_DATE_PROCEDURE_RE.search(t) and re.search(r"\d", t))
    return any(c.isdigit() for c in t)


def _strict_damages_signal(text: str | None) -> bool:
    if not text:
        return False
    if has_explicit_monetary_amount(text):
        return True
    t = text.casefold()
    return bool(re.search(r"\bsum of\b", t) and re.search(r"[£$€]|\d", text))


def _strict_parties_signal(text: str | None) -> bool:
    if not text:
        return False
    if has_identity_signal(text):
        return True
    if _PARTY_ROLE_RE.search(text) and _PROPER_NAME_IN_TEXT_RE.search(text):
        return True
    return False


def _strict_court_signal(text: str | None) -> bool:
    if not text:
        return False
    if not _COURT_FORUM_RE.search(text):
        return False
    if _CASE_ID_RE.search(text):
        return True
    return len(text.strip()) > 30 and bool(_PROPER_NAME_IN_TEXT_RE.search(text))


def is_facet_weakly_satisfied(
    label: str,
    text: str | None,
    *,
    require_dates: bool = False,
) -> bool:
    """True when text nominally matches a facet but lacks strict evidence."""
    facet = label.casefold()
    if "damage" in facet or "amount" in facet or facet == "damages":
        if not text:
            return True
        return not _strict_damages_signal(text)
    if "date" in facet or "when" in facet:
        if not text:
            return True
        return not _strict_date_signal(text, require_strict=require_dates)
    if "part" in facet or "ident" in facet or facet == "parties":
        if not text:
            return True
        return not _strict_parties_signal(text)
    if "court" in facet or "forum" in facet:
        if not text:
            return True
        return not _strict_court_signal(text)
    return False


def _sub_question_satisfied(
    sq: SubQuestion,
    hits: list[SearchHit],
    *,
    require_dates: bool = False,
) -> str | None:
    label = sq.label.casefold()
    for h in hits:
        text = h.text_content or ""
        text_cf = text.casefold()
        if "name" in label or "identity" in label or label == "parties":
            if _strict_parties_signal(text):
                return h.chunk_id
        if "age" in label:
            if any(w in text_cf for w in ("aged", "years", "year old", "infant")):
                return h.chunk_id
        if "date" in label or "accident" in label or "when" in label:
            if _strict_date_signal(text, require_strict=require_dates):
                return h.chunk_id
        if "amount" in label or "damage" in label:
            if _strict_damages_signal(text):
                return h.chunk_id
        if "court" in label or "forum" in label:
            if _strict_court_signal(text):
                return h.chunk_id
        terms = [t.casefold() for t in sq.fts_terms if t]
        if terms and any(t in text_cf for t in terms):
            if label in {"damages", "dates", "parties", "court"}:
                if is_facet_weakly_satisfied(label, text, require_dates=require_dates):
                    continue
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
    require_dates = understanding.require_dates_facet

    sq_map = rank_diag.get("sub_question_coverage") or {}
    for sq in understanding.sub_questions:
        cid = sq_map.get(sq.label) if isinstance(sq_map, dict) else None
        if cid and any(h.chunk_id == cid for h in hits):
            hit = next(h for h in hits if h.chunk_id == cid)
            weak = is_facet_weakly_satisfied(
                sq.label, hit.text_content, require_dates=require_dates,
            )
            if weak:
                report.sub_question_coverage[sq.label] = None
                report.facets_weak[sq.label] = True
                report.facets_covered[sq.label] = False
            else:
                report.sub_question_coverage[sq.label] = cid
                report.facets_covered[sq.label] = True
                report.facets_weak[sq.label] = False
        else:
            found = _sub_question_satisfied(sq, hits, require_dates=require_dates)
            weak = False
            if found is None and sq.fts_terms:
                for h in hits:
                    text_cf = (h.text_content or "").casefold()
                    if any(t.casefold() in text_cf for t in sq.fts_terms if t):
                        if is_facet_weakly_satisfied(
                            sq.label, h.text_content, require_dates=require_dates,
                        ):
                            weak = True
                            break
            report.sub_question_coverage[sq.label] = found
            report.facets_covered[sq.label] = found is not None
            report.facets_weak[sq.label] = weak

    pass_hit = _pass_labels_with_hits(hits, understanding.search_passes)
    for label, covered in pass_hit.items():
        report.pass_labels_covered[label] = covered

    return report


def _coverage_needs_fill(report: CoverageReport) -> bool:
    if any(v is None for v in report.sub_question_coverage.values()):
        return True
    if any(report.facets_weak.values()):
        return True
    return any(not v for v in report.pass_labels_covered.values())


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


def _gap_fill_passes(
    understanding: QueryUnderstanding,
    report: CoverageReport,
) -> list[SearchPass]:
    missing: list[SearchPass] = []
    for sq in understanding.sub_questions:
        uncovered = not report.sub_question_coverage.get(sq.label)
        weak = report.facets_weak.get(sq.label, False)
        if (uncovered or weak) and sq.fts_terms:
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
    overview = understanding.intent == "case_overview"
    if not settings.query_planner_repair_on_zero_hits and not overview:
        return pool, []

    if not _coverage_needs_fill(report):
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


def pin_facet_pages(
    db: Session,
    hits: list[SearchHit],
    understanding: QueryUnderstanding,
    report: CoverageReport,
    *,
    workspace_id: str,
    document_ids: list[str] | None,
    top_k: int,
) -> list[SearchHit]:
    """Pin entity-index pages for facets still missing after gap-fill."""
    if understanding.intent != "case_overview":
        return hits

    from app.services.entity_page_context import hits_from_ranked_pages
    from app.services.entity_page_context import ScoredPage, _facet_entity_pages_for_document

    missing_facets = [
        sq.label
        for sq in understanding.sub_questions
        if not report.sub_question_coverage.get(sq.label) or report.facets_weak.get(sq.label)
    ]
    if not missing_facets:
        return hits

    doc_ids = document_ids or sorted({h.document_id for h in hits})
    if not doc_ids:
        return hits

    pinned: list[SearchHit] = list(hits)
    seen_pages = {(h.document_id, h.page_number) for h in hits}

    for doc_id in doc_ids[:2]:
        extra_pages = _facet_entity_pages_for_document(db, workspace_id, doc_id)
        ranked = [ScoredPage(page_number=p, score=0.0) for p in sorted(extra_pages)[:8]]
        for sp in ranked:
            if (doc_id, sp.page_number) in seen_pages:
                continue
            page_hits = hits_from_ranked_pages(db, doc_id, [sp])
            pinned.extend(page_hits)
            seen_pages.add((doc_id, sp.page_number))

    if len(pinned) > top_k:
        from app.services.entity_page_chunks import dedupe_hits_by_page

        pinned = dedupe_hits_by_page(pinned)[:top_k]
    return pinned


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


def _coverage_report_dict(report: CoverageReport) -> dict:
    facet_coverage: dict[str, dict] = {}
    for label, covered in report.facets_covered.items():
        cid = report.sub_question_coverage.get(label)
        hit_page = None
        has_amount = False
        has_date = False
        if cid:
            has_amount = True  # populated below from hits if available
        facet_coverage[label] = {
            "satisfied": covered and not report.facets_weak.get(label, False),
            "chunk_id": cid,
            "weak": report.facets_weak.get(label, False),
        }
        _ = hit_page, has_amount, has_date

    return {
        "sub_question_coverage": report.sub_question_coverage,
        "pass_labels_covered": report.pass_labels_covered,
        "facets_covered": report.facets_covered,
        "facets_weak": report.facets_weak,
        "facet_coverage": facet_coverage,
        "gaps_filled": report.gaps_filled,
    }


def enrich_facet_coverage_diagnostics(
    report_dict: dict,
    hits: list[SearchHit],
    understanding: QueryUnderstanding,
) -> dict:
    """Add page-level facet diagnostics for observability."""
    by_id = {h.chunk_id: h for h in hits}
    facet_cov = report_dict.get("facet_coverage") or {}
    for label, info in facet_cov.items():
        cid = info.get("chunk_id") if isinstance(info, dict) else None
        hit = by_id.get(cid) if cid else None
        if not hit:
            continue
        text = hit.text_content or ""
        info["page"] = hit.page_number
        if "damage" in label.casefold():
            info["has_explicit_amount"] = _strict_damages_signal(text)
        if "date" in label.casefold():
            info["strict"] = understanding.require_dates_facet
            info["has_calendar_date"] = _strict_date_signal(
                text, require_strict=understanding.require_dates_facet,
            )
    report_dict["facet_coverage"] = facet_cov
    return report_dict


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
    gap_fill_rounds: int = 1,
    page_level_pool: bool = False,
) -> tuple[list[SearchHit], dict]:
    """Expand, multi-round gap-fill, re-verify coverage, and sandwich-order for synthesis."""
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
    all_filled: list[str] = []
    rounds = 0

    for _ in range(max(1, gap_fill_rounds)):
        if not _coverage_needs_fill(report):
            break
        pool, filled = gap_fill_retrieval(
            db,
            query=query,
            understanding=understanding,
            workspace_id=workspace_id,
            document_ids=document_ids,
            pool=pool,
            report=report,
        )
        rounds += 1
        if filled:
            all_filled.extend(filled)
            merged = sorted(pool.values(), key=lambda h: h.score)
            expanded, expand_diag = expand_context_hits(
                db,
                merged[:max_chunks],
                bundles=bundles,
                max_chunks=max_chunks,
                max_per_page=max_per_page,
            )
            report = compute_coverage_report(
                expanded, understanding, rank_diagnostics=rank_diagnostics,
            )
            pool = {h.chunk_id: h for h in expanded}
        else:
            break

    expanded = pin_facet_pages(
        db,
        expanded,
        understanding,
        report,
        workspace_id=workspace_id,
        document_ids=document_ids,
        top_k=top_k,
    )
    if page_level_pool:
        from app.services.entity_page_chunks import dedupe_hits_by_page

        expanded = dedupe_hits_by_page(expanded)[:top_k]
        report = compute_coverage_report(
            expanded, understanding, rank_diagnostics=rank_diagnostics,
        )

    sq_cov = report.sub_question_coverage
    ordered = sandwich_order_hits(expanded, sub_question_coverage=sq_cov)
    if len(ordered) > top_k:
        ordered = ordered[:top_k]

    coverage_report = _coverage_report_dict(report)
    enrich_facet_coverage_diagnostics(coverage_report, ordered, understanding)

    diagnostics = {
        **expand_diag,
        "coverage_report": coverage_report,
        "context_max_chunks": max_chunks,
        "sandwich_ordered": len(ordered) > 2,
        "expansion_rounds": rounds,
        "overview_gap_fill": all_filled,
        "page_level_pool": page_level_pool,
        "context_expansion_skipped": False,
    }
    return ordered, diagnostics
