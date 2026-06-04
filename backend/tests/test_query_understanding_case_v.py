from app.config import settings
from app.services.query_understanding import _case_name_terms, understand_query


def test_case_name_terms_lowercase_winzo_v_google():
    terms = _case_name_terms("list all case details on winzo games v google")
    assert terms is not None
    assert "winzo" in terms
    assert "google" in terms


def test_winzo_case_details_not_google_listing(monkeypatch):
    monkeypatch.setattr(settings, "enable_llm_query_understanding", False)
    monkeypatch.setattr(settings, "enable_regex_nlp", True)
    u = understand_query("list all case details on winzo games v google")
    assert u.intent == "case_overview"
    assert u.target_entity is None


def test_against_google_stays_listing(monkeypatch):
    monkeypatch.setattr(settings, "enable_llm_query_understanding", False)
    monkeypatch.setattr(settings, "enable_regex_nlp", True)
    u = understand_query("list all case details against google")
    assert u.intent == "entity_matter_listing"
