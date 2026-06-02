from __future__ import annotations

from app.schemas import SearchHit
from app.services.context_coverage import compute_coverage_report


def facet_recall(
    hits: list[SearchHit],
    label: dict,
    *,
    coverage_report: dict | None = None,
) -> float:
    """COV-03: fraction of required facets with supporting evidence in context."""
    facets = label.get("facets") or []
    required = [f for f in facets if f.get("required", True)]
    if not required:
        return 1.0

    hit_pages = {(h.document_id, h.page_number) for h in hits}
    sq_cov = (coverage_report or {}).get("sub_question_coverage") or {}
    covered = 0
    for facet in required:
        label_name = facet.get("label", "")
        if label_name and sq_cov.get(label_name):
            covered += 1
            continue
        gold_pages = facet.get("gold_pages") or label.get("gold_pages") or []
        if isinstance(gold_pages, list) and gold_pages and isinstance(gold_pages[0], int):
            doc_id = label.get("document_id")
            if doc_id and any((doc_id, p) in hit_pages for p in gold_pages):
                covered += 1
                continue
        if label_name and any(label_name.casefold() in (h.text_content or "").casefold() for h in hits):
            covered += 1
    return covered / len(required)


def cov01_pass(hits: list[SearchHit], understanding, rank_diagnostics: dict | None) -> bool:
    """COV-01: each planner sub-question has a supporting chunk in context."""
    if not understanding.sub_questions:
        return len(hits) > 0
    report = compute_coverage_report(hits, understanding, rank_diagnostics=rank_diagnostics)
    return all(v is not None for v in report.sub_question_coverage.values())


def cov02_pass(hits: list[SearchHit], *, min_pages: int = 3) -> bool:
    """COV-02: overview breadth — distinct substantive pages."""
    pages = {(h.document_id, h.page_number) for h in hits}
    substantive = [
        h for h in hits
        if len((h.text_content or "").strip()) >= 40
    ]
    sub_pages = {(h.document_id, h.page_number) for h in substantive}
    return len(pages) >= min_pages and len(sub_pages) >= min(min_pages, 2)


def planner_intent_match(understanding, label: dict) -> bool | None:
    expected = label.get("expected_intent")
    if not expected:
        return None
    return understanding.intent == expected
