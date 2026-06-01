from app.config import settings
from app.services.query_understanding import understand_query


def test_list_cases_against_google_is_entity_matter_listing():
    settings.enable_llm_query_understanding = False
    u = understand_query("list all cases against Google LLC")
    assert u.intent == "entity_matter_listing"
    assert u.retrieval_mode == "SIMPLE"
    assert any(c.type == "party" and "google" in c.canonical for c in u.constraints)


def test_chester_single_case_stays_case_overview():
    settings.enable_llm_query_understanding = False
    u = understand_query("List all case details involving Chester v Waverley")
    assert u.intent == "case_overview"
    assert u.intent != "entity_matter_listing"


def test_cases_against_entity_phrase():
    settings.enable_llm_query_understanding = False
    u = understand_query("cases against Google India Private Limited")
    assert u.intent == "entity_matter_listing"
