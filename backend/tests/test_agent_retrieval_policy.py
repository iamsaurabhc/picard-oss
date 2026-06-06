"""Agent retrieval policy (breadth × persona)."""

from app.config import settings
from app.services.agent_retrieval_policy import build_agent_retrieval_policy, resolve_breadth
from app.services.query_understanding import understand_query


def test_scoped_multi_doc_catalog_breadth(monkeypatch):
    monkeypatch.setattr(settings, "enable_llm_query_understanding", False)
    monkeypatch.setattr(settings, "enable_regex_nlp", True)
    q = "tell me everything about Google in these filings"
    doc_ids = [f"doc-{i}" for i in range(13)]
    u = understand_query(q)
    breadth = resolve_breadth(q, u, document_ids=doc_ids)
    assert breadth == "catalog"
    policy = build_agent_retrieval_policy(
        q,
        agent_profile="firm",
        document_ids=doc_ids,
        understanding=u,
    )
    assert policy.breadth == "catalog"
    assert policy.documents_in_scope == 13
    assert policy.map_max_docs == min(settings.firm_agent_listing_map_max_docs, 13)


def test_google_cuts_listing_intent_override(monkeypatch):
    monkeypatch.setattr(settings, "enable_llm_query_understanding", False)
    monkeypatch.setattr(settings, "enable_regex_nlp", True)
    q = "list all case details involving google v CUTS"
    policy = build_agent_retrieval_policy(q, agent_profile="firm", document_ids=None)
    assert policy.breadth == "catalog"
    assert policy.intent_override == "entity_matter_listing"


def test_llm_case_overview_query_still_catalog_breadth():
    """LLM often returns case_overview for 'list all case details involving X v Y'."""
    q = "list all case details involving google v CUTS"
    u = understand_query(q)
    policy = build_agent_retrieval_policy(q, agent_profile="firm", understanding=u)
    assert policy.breadth == "catalog"
    assert policy.intent_override == "entity_matter_listing"


def test_court_profile_lower_map_cap():
    policy = build_agent_retrieval_policy(
        "list all cases against Google",
        agent_profile="court",
        document_ids=["d1", "d2", "d3"],
    )
    assert policy.agent_profile == "court"
    assert policy.map_max_docs <= settings.court_agent_listing_map_max_docs
