from app.config import settings
from app.services.query_understanding import understand_query


def test_list_cases_against_google_is_entity_matter_listing(mock_query_planner):
    mock_query_planner("google_listing")
    u = understand_query("list all cases against Google LLC")
    assert u.intent == "entity_matter_listing"
    assert u.retrieval_mode == "SIMPLE"
    assert u.used_llm is True
    assert u.target_entity is not None
    assert "google" in u.target_entity.canonical
    assert any(c.type == "party" and "google" in c.canonical for c in u.constraints)


def test_chester_single_case_stays_case_overview(mock_query_planner):
    mock_query_planner("chester_overview")
    u = understand_query("List all case details involving Chester v Waverley")
    assert u.intent == "case_overview"
    assert u.intent != "entity_matter_listing"


def test_cases_against_entity_phrase(mock_query_planner):
    mock_query_planner("google_india_listing")
    u = understand_query("cases against Google India Private Limited")
    assert u.intent == "entity_matter_listing"


def test_listing_token_fallback_without_llm():
    settings.enable_llm_query_understanding = False
    u = understand_query("list all cases against Google LLC")
    assert u.intent == "entity_matter_listing"
    assert any(c.type == "party" and "google" in c.canonical for c in u.constraints)
