from app.config import settings
from app.services.query_understanding import _case_name_terms, understand_query


def test_case_name_terms_citation_passage_query():
    terms = _case_name_terms(
        "Summarize every passage discussing Ovens v Liverpool across the judgment"
    )
    assert terms == ["ovens", "liverpool"]

    terms_h = _case_name_terms(
        "Summarize every passage discussing Hambrook v Stokes across the judgment"
    )
    assert terms_h == ["hambrook", "stokes"]


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


def test_google_v_cuts_listing_with_involving(monkeypatch):
    monkeypatch.setattr(settings, "enable_llm_query_understanding", False)
    monkeypatch.setattr(settings, "enable_regex_nlp", True)
    q = "list all case details involving google v CUTS"
    u = understand_query(q)
    assert u.intent == "entity_matter_listing"
    assert u.intent != "case_overview"
    party_canonicals = {c.canonical for c in u.constraints if c.type == "party"}
    assert "google" in " ".join(party_canonicals).casefold() or any(
        "google" in c.casefold() for c in party_canonicals
    )
    assert any("cuts" in c.casefold() for c in party_canonicals)


def test_list_all_case_details_involving_not_overview(monkeypatch):
    monkeypatch.setattr(settings, "enable_llm_query_understanding", False)
    monkeypatch.setattr(settings, "enable_regex_nlp", True)
    u = understand_query("list all case details involving Alphabet and CUTS")
    assert u.intent == "entity_matter_listing"
