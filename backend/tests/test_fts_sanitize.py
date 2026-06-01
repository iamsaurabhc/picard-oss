from app.services.fts_query_builder import build_fts_match_string
from app.services.query_understanding import FtsPlan


def test_expanded_case_name_uses_structured_and():
    plan = FtsPlan(
        must_terms=["chester", "waverley"],
        phrases=["chester waverley", "chester versus waverley"],
        operator="AND",
    )
    fts = build_fts_match_string(plan)
    assert "chester waverley" in fts
    assert "chester" in fts and "waverley" in fts
    assert fts.count(" OR ") == 0 or "chester versus waverley" in fts


def test_short_entity_query_uses_and():
    plan = FtsPlan(must_terms=["chester", "waverley"], operator="AND")
    assert build_fts_match_string(plan) == "chester waverley"


def test_broad_nl_query_uses_or():
    plan = FtsPlan(
        must_terms=["case", "context", "supreme", "court", "plaintiff", "damages", "negligence", "liability"],
        operator="OR",
    )
    fts = build_fts_match_string(plan)
    assert " OR " in fts
    assert fts.count(" OR ") >= 3
