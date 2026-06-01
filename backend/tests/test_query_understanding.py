import json
from unittest.mock import patch

from app.config import settings
from app.services.fts_query_builder import build_fts_match_string
from app.services.query_understanding import FtsPlan, QueryUnderstanding, understand_query


def test_build_fts_and_case_names():
    plan = FtsPlan(must_terms=["chester", "waverley"], phrases=["chester waverley"], operator="AND")
    assert build_fts_match_string(plan) == "chester waverley"


def test_build_fts_or_mode():
    plan = FtsPlan(must_terms=["plaintiff"], should_terms=["damages", "compensation"], operator="OR")
    fts = build_fts_match_string(plan)
    assert " OR " in fts
    assert "plaintiff" in fts


def test_understand_query_fallback_no_llm():
    settings.enable_llm_query_understanding = False
    u = understand_query("chester waverley negligence")
    assert u.used_llm is False
    assert "chester" in u.fts.must_terms or "waverley" in u.fts.must_terms


def test_understand_query_llm_success():
    settings.enable_llm_query_understanding = True
    payload = {
        "retrieval_mode": "SIMPLE",
        "intent": "factual_lookup",
        "constraints": [],
        "fts": {
            "must_terms": ["chester", "waverley"],
            "should_terms": [],
            "phrases": ["chester waverley"],
            "operator": "AND",
        },
        "search_passes": [{"label": "anchor", "fts_terms": ["chester", "waverley"], "pin_best": False}],
        "confidence": 0.9,
    }
    with patch("app.services.query_understanding.completion", return_value=json.dumps(payload)):
        u = understand_query("List all case details involving Chester v Waverley")
    assert u.used_llm is True
    assert u.fts.must_terms == ["chester", "waverley"]


def test_understand_query_merges_rule_constraints():
    settings.enable_llm_query_understanding = True
    payload = {
        "retrieval_mode": "SIMPLE",
        "intent": "general",
        "constraints": [],
        "fts": {"must_terms": ["damages"], "should_terms": [], "phrases": [], "operator": "AND"},
        "confidence": 0.8,
    }
    with patch("app.services.query_understanding.completion", return_value=json.dumps(payload)):
        u = understand_query("plaintiff claimed damages in the sum of £1,000")
    types = {c.type for c in u.constraints}
    assert "amount" in types
