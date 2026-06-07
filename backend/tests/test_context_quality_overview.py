"""Regression tests for overview context quality (quality-independent of latency profile)."""

from __future__ import annotations

from app.config import settings
from app.schemas import SearchHit
from app.services.case_scoping import resolve_case_document_ids
from app.services.citation_kernel import rank_and_cover_hits
from app.services.citations import build_citation_map, build_system_prompt
from app.services.context_coverage import (
    _sub_question_satisfied,
    compute_coverage_report,
    gap_fill_retrieval,
    is_facet_weakly_satisfied,
)
from app.services.query_understanding import (
    QueryUnderstanding,
    SubQuestion,
    _case_name_terms,
    understand_query,
)
from app.services.retrieval_depth import infer_depth_demand, resolve_retrieval_depth


def _hit(chunk_id: str, doc_id: str, page: int, text: str) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        document_id=doc_id,
        page_number=page,
        text_content=text,
        heading_path=None,
        section_key=None,
        bbox=None,
        score=-5.0,
    )


def test_case_name_waverly_v_chester_scoping():
    terms = _case_name_terms(
        "give detailed summary of the case Waverly v Chester, sections, context, dates"
    )
    assert terms is not None
    assert "chester" in terms
    assert "detailed" not in terms
    assert "waverly" in terms


def test_infer_depth_exhaustive_for_detailed_overview():
    u = QueryUnderstanding(
        intent="case_overview",
        coverage_goal="broad matter summary",
        require_dates_facet=True,
        sub_questions=[
            SubQuestion(label="parties", question="?", fts_terms=["plaintiff"]),
            SubQuestion(label="damages", question="?", fts_terms=["damages"]),
            SubQuestion(label="dates", question="?", fts_terms=["date"]),
        ],
    )
    tier, signals = infer_depth_demand(
        "give detailed summary of the case Waverly v Chester, sections, context, dates",
        u,
    )
    assert tier == "exhaustive"
    assert "intent:case_overview" in signals
    assert "explicit:dates" in signals


def test_weak_damages_satisfaction_triggers_gap_fill():
    rhetoric = _hit("rhetoric", "d1", 9, "The question of damages was discussed at length.")
    assert is_facet_weakly_satisfied("damages", rhetoric.text_content)
    report = compute_coverage_report(
        [rhetoric],
        QueryUnderstanding(
            intent="case_overview",
            sub_questions=[
                SubQuestion(label="damages", question="amount?", fts_terms=["damages"]),
            ],
        ),
    )
    assert report.sub_question_coverage.get("damages") is None
    assert report.facets_weak.get("damages") is True


def test_strict_damages_accepts_explicit_amount():
    amount_hit = _hit("amt", "d1", 3, "The plaintiff claimed damages in the sum of £1,000.")
    cid = _sub_question_satisfied(
        SubQuestion(label="damages", question="?", fts_terms=["damages"]),
        [amount_hit],
    )
    assert cid == "amt"


def test_date_noise_rejected_for_dates_facet():
    noise = _hit("cite", "d1", 1, "See 78FCR456 and SASR citations in the header.")
    assert not _sub_question_satisfied(
        SubQuestion(label="dates", question="?", fts_terms=["date"]),
        [noise],
        require_dates=True,
    )
    calendar = _hit("cal", "d1", 6, "The matter was heard on 15 March 1924.")
    assert _sub_question_satisfied(
        SubQuestion(label="dates", question="?", fts_terms=["date"]),
        [calendar],
        require_dates=True,
    )


def test_facet_grouped_overview_prompt():
    hits = [
        _hit("p3", "doc", 3, "The plaintiff claimed damages in the sum of £1,000."),
        _hit("p1", "doc", 1, "Between Waverley and Chester, the infant son died."),
    ]
    u = QueryUnderstanding(
        intent="case_overview",
        sub_questions=[
            SubQuestion(label="damages", question="?", fts_terms=["damages"]),
            SubQuestion(label="dates", question="?", fts_terms=["date"]),
        ],
    )
    coverage = {
        "sub_question_coverage": {"damages": "p3", "dates": "p1"},
    }
    cmap = build_citation_map(
        hits,
        excerpt_chars=1500,
        question="overview",
        sub_questions=u.sub_questions,
        prefer_amounts=True,
        page_level=True,
        intent="case_overview",
    )
    prompt = build_system_prompt(
        cmap,
        intent="case_overview",
        sub_questions=u.sub_questions,
        sub_question_coverage=coverage["sub_question_coverage"],
        excerpt_cap=1500,
    )
    assert "### Evidence for: Damages" in prompt
    assert "£1,000" in prompt
    assert "### Evidence for: Dates" in prompt


def test_quality_profile_chester_includes_1000_in_prompt():
    """User failure mode: £1,000 must appear in prompt Sources, not only stored preview."""
    text = (
        "In an action by the plaintiff against the defendant, "
        "the plaintiff claimed damages in the sum of £1,000 for the death of his infant son."
    )
    hits = [_hit("page3", "chester", 3, text)]
    u = QueryUnderstanding(
        intent="case_overview",
        coverage_goal="broad matter summary",
        require_dates_facet=True,
        sub_questions=[
            SubQuestion(label="damages", question="?", fts_terms=["damages", "sum"]),
            SubQuestion(label="dates", question="?", fts_terms=["date", "filed"]),
        ],
    )
    policy = resolve_retrieval_depth(
        "give detailed summary of the case Waverly v Chester, sections, context, dates",
        u,
        is_overview=True,
    )
    cmap = build_citation_map(
        hits,
        excerpt_chars=policy.prompt_excerpt_cap,
        question="give detailed summary Waverly v Chester",
        sub_questions=u.sub_questions,
        prefer_amounts=True,
        page_level=True,
        intent="case_overview",
    )
    prompt = build_system_prompt(
        cmap,
        intent="case_overview",
        sub_questions=u.sub_questions,
        sub_question_coverage={"damages": "page3"},
        excerpt_cap=policy.prompt_excerpt_cap,
    )
    assert "£1,000" in prompt
    assert policy.depth_tier == "exhaustive"
    assert policy.prompt_excerpt_cap >= 1500


def test_page_level_path_runs_full_coverage(corpus_session, monkeypatch):
    """Overview page-level path must not set context_expansion_skipped."""
    from sqlalchemy import select

    from app.db.models import Chunk

    monkeypatch.setattr(settings, "enable_context_expansion", True)
    row = corpus_session.scalars(select(Chunk).limit(1)).first()
    if not row:
        return
    hits = [_hit(row.id, row.document_id, row.page_number, row.text_content or "sample text")]
    u = QueryUnderstanding(
        intent="case_overview",
        sub_questions=[
            SubQuestion(label="damages", question="?", fts_terms=["damages"]),
        ],
    )
    policy = resolve_retrieval_depth("overview", u, is_overview=True)
    covered, diag = rank_and_cover_hits(
        corpus_session,
        query="case overview",
        understanding=u,
        hits=hits,
        workspace_id="ws",
        document_ids=[row.document_id],
        bundles=None,
        top_k=policy.top_k,
        rank_mode="coverage",
        page_level_pool=True,
        depth_policy=policy,
    )
    assert diag.get("context_expansion_skipped") is False
    assert "coverage_report" in diag
    assert len(covered) >= 1


def test_gap_fill_runs_for_overview_without_quality_profile(monkeypatch, corpus_session):
    monkeypatch.setattr(settings, "query_planner_repair_on_zero_hits", False)
    u = QueryUnderstanding(
        intent="case_overview",
        sub_questions=[
            SubQuestion(label="damages", question="?", fts_terms=["damages", "sum"]),
        ],
    )
    report = compute_coverage_report([], u)
    pool: dict[str, SearchHit] = {}
    _, filled = gap_fill_retrieval(
        corpus_session,
        query="damages sum",
        understanding=u,
        workspace_id="eca7aebb-0b4d-433d-8e73-9144c04eb0d7",
        document_ids=None,
        pool=pool,
        report=report,
    )
    assert isinstance(filled, list)


def test_case_name_terms_understand_query(monkeypatch):
    monkeypatch.setattr(settings, "enable_llm_query_understanding", False)
    monkeypatch.setattr(settings, "enable_regex_nlp", True)
    q = "give detailed summary of the case Waverly v Chester, sections, context, dates"
    u = understand_query(q)
    assert u.intent == "case_overview"
    assert u.require_dates_facet is True
    terms = _case_name_terms(q)
    assert terms and "waverly" in terms and "chester" in terms


def test_resolve_case_document_fuzzy_party(corpus_session):
    resolved = resolve_case_document_ids(
        corpus_session,
        "eca7aebb-0b4d-433d-8e73-9144c04eb0d7",
        ["waverly", "chester"],
        None,
    )
    if resolved:
        assert len(resolved) >= 1
