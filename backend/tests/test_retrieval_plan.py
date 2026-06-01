import json
from unittest.mock import patch

from app.config import settings
from app.services.query_understanding import (
    SearchPass,
    SubQuestion,
    _fallback_search_passes,
    _is_valid_amount_canonical,
    _parse_sub_questions,
    _passes_from_sub_questions,
    _validate_retrieval_plan,
    understand_query,
    QueryUnderstanding,
)


def test_no_hardcoded_corpus_tokens_in_fallback_passes(mock_query_planner):
    mock_query_planner("chester_overview")
    u = understand_query("List all case details involving Smith v Jones")
    labels = {p.label for p in u.search_passes}
    assert "parties" in labels or "central_facts" in labels
    all_terms = " ".join(t for p in u.search_passes for t in p.fts_terms).casefold()
    for forbidden in ("chester", "waverley", "1938", "1939", "son trench"):
        assert forbidden not in all_terms


def test_factual_amount_query_forces_simple():
    settings.enable_llm_query_understanding = False
    settings.enable_regex_nlp = True
    u = understand_query("amount claimed by janet smith?")
    assert u.intent == "factual_lookup"
    assert u.retrieval_mode == "SIMPLE"
    assert len(u.fts.must_terms) <= 2


def test_invalid_amount_constraint_dropped():
    settings.enable_llm_query_understanding = True
    payload = {
        "retrieval_mode": "MULTI_CONSTRAINT",
        "intent": "obligations",
        "constraints": [{"type": "amount", "canonical": "amount claimed", "surfaces": []}],
        "fts": {"must_terms": ["damages"], "should_terms": [], "phrases": [], "operator": "AND"},
        "search_passes": [],
        "confidence": 0.8,
    }
    with patch("app.services.query_understanding.completion", return_value=json.dumps(payload)):
        u = understand_query("amount claimed by party")
    amount_constraints = [c for c in u.constraints if c.type == "amount"]
    assert not any(c.canonical == "amount claimed" for c in amount_constraints)
    assert any("dropped_invalid_amount" in m for m in u.rule_merges)


def test_llm_passes_not_merged_with_regex_fallback():
    settings.enable_llm_query_understanding = True
    payload = {
        "retrieval_mode": "SIMPLE",
        "intent": "case_overview",
        "constraints": [],
        "fts": {"must_terms": ["smith", "jones"], "should_terms": [], "phrases": [], "operator": "AND"},
        "search_passes": [{"label": "parties", "fts_terms": ["plaintiff", "defendant"], "pin_best": True}],
        "confidence": 0.9,
    }
    with patch("app.services.query_understanding.completion", return_value=json.dumps(payload)):
        u = understand_query("List all case details involving Smith v Jones")
    labels = {p.label for p in u.search_passes}
    assert labels == {"parties"}


def test_fallback_search_passes_arbitrary_parties():
    passes = _fallback_search_passes(
        "List all details for Alpha v Beta Corporation",
        "case_overview",
        case_terms=["alpha", "beta"],
    )
    assert passes
    terms = " ".join(t for p in passes for t in p.fts_terms).casefold()
    assert "chester" not in terms
    assert "waverley" not in terms


def test_valid_amount_canonical():
    assert _is_valid_amount_canonical("1000_gbp")
    assert not _is_valid_amount_canonical("amount claimed")


def test_facet_queries_populated_from_search_passes():
    u = QueryUnderstanding(
        search_passes=[
            SearchPass(label="damages", fts_terms=["damages", "sum"]),
            SearchPass(label="court", fts_terms=["court"]),
        ],
    )
    u = _validate_retrieval_plan(u, "overview query", used_llm=False)
    assert u.facet_queries.get("damages") == ["damages", "sum"]


def test_compound_factual_fallback_single_generic_pass():
    settings.enable_llm_query_understanding = False
    settings.enable_regex_nlp = True
    q = "janet chester son's name? age? date of accident?"
    u = understand_query(q)
    assert u.intent == "factual_lookup"
    assert u.retrieval_mode == "SIMPLE"
    assert len(u.search_passes) >= 1
    assert len(u.fts.must_terms) <= 2


def test_compound_factual_llm_sub_questions():
    settings.enable_llm_query_understanding = True
    payload = {
        "retrieval_mode": "SIMPLE",
        "intent": "factual_lookup",
        "constraints": [],
        "fts": {"must_terms": ["janet", "chester"], "should_terms": [], "phrases": [], "operator": "AND"},
        "sub_questions": [
            {"label": "name", "question": "son's name", "fts_terms": ["janet", "son"], "pin_best": True},
            {"label": "age", "question": "son's age", "fts_terms": ["son", "aged"], "pin_best": True},
        ],
        "search_passes": [],
        "confidence": 0.9,
    }
    with patch("app.services.query_understanding.completion", return_value=json.dumps(payload)):
        u = understand_query("janet chester son's name? age? date of accident?")
    assert len(u.sub_questions) == 2
    assert len(u.search_passes) == 2
    assert u.search_passes[0].label == "name"


def test_parse_sub_questions_and_passes():
    data = [
        {"label": "age", "question": "How old?", "fts_terms": ["son", "aged"]},
    ]
    subs = _parse_sub_questions(data)
    passes = _passes_from_sub_questions(subs)
    assert subs[0].label == "age"
    assert passes[0].fts_terms == ["son", "aged"]


def test_compound_factual_never_seven_term_and():
    settings.enable_llm_query_understanding = False
    u = understand_query("janet chester son's name? age? date of accident?")
    assert len(u.fts.must_terms) <= 2
