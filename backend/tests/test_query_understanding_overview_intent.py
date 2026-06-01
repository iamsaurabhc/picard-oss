from app.config import settings
from app.services.query_understanding import understand_query


def test_list_all_case_details_is_case_overview():
    settings.enable_llm_query_understanding = False
    u = understand_query("List all case details involving Chester v Waverley")
    assert u.intent == "case_overview"
    assert u.retrieval_mode == "SIMPLE"
    assert "parties" in u.overview_facets
    assert u.facet_queries.get("damages")


def test_pinpoint_damages_not_overview():
    settings.enable_llm_query_understanding = False
    u = understand_query("What damages did the plaintiff claim?")
    assert u.intent == "factual_lookup"
