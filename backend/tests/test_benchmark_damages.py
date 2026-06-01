import pytest

from app.services.constraint_planner import plan_query
from app.services.entity_index import (
    AMOUNT_PATTERN,
    LEGAL_ACTOR_PATTERN,
    extract_mentions_from_text,
    lookup_pages_for_constraint,
    normalize_amount,
)
from app.services.fts_search import fts_search
from app.services.search import execute_search
from app.schemas import SearchRequest
from tests.corpus_constants import (
    BENCHMARK_AMOUNT_CANONICAL,
    BENCHMARK_CHUNK_ID,
    BENCHMARK_LINE,
    BENCHMARK_PAGE,
    BENCHMARK_PARTY_CANONICAL,
    BENCHMARK_QUERIES,
    DOCUMENT_ID,
    WORKSPACE_ID,
)


def test_normalize_amount():
    assert normalize_amount("£1,000") == "1000_gbp"


def test_extract_benchmark_mentions():
    mentions = extract_mentions_from_text(BENCHMARK_LINE, early_doc=False)
    types = {m.entity_type for m in mentions}
    assert "amount" in types
    assert "party" in types
    assert any(m.canonical_value == "1000_gbp" for m in mentions)
    assert any(m.canonical_value == "the plaintiff" for m in mentions)


@pytest.mark.corpus
def test_benchmark_entities_on_page_3(corpus_session):
    amount_pages = lookup_pages_for_constraint(
        corpus_session, WORKSPACE_ID, "amount", BENCHMARK_AMOUNT_CANONICAL, [DOCUMENT_ID]
    )
    party_pages = lookup_pages_for_constraint(
        corpus_session, WORKSPACE_ID, "party", BENCHMARK_PARTY_CANONICAL, [DOCUMENT_ID]
    )
    assert (DOCUMENT_ID, BENCHMARK_PAGE) in amount_pages
    assert (DOCUMENT_ID, BENCHMARK_PAGE) in party_pages


@pytest.mark.corpus
def test_benchmark_exact_fts_retrieves_gold_chunk(corpus_session):
    hits = fts_search(
        corpus_session,
        query=BENCHMARK_QUERIES["exact"],
        workspace_id=WORKSPACE_ID,
        document_ids=[DOCUMENT_ID],
        top_k=5,
    )
    assert hits
    assert hits[0].chunk_id == BENCHMARK_CHUNK_ID
    assert BENCHMARK_LINE in hits[0].text_content


@pytest.mark.corpus
def test_benchmark_complex_search(corpus_client):
    r = corpus_client.post(
        "/search",
        json={
            "query": BENCHMARK_QUERIES["complex"],
            "workspace_id": WORKSPACE_ID,
            "retrieval_mode": "simple",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "SIMPLE"
    assert not data["refused"]
    chunk_ids = [h["chunk_id"] for h in data["hits"]]
    assert BENCHMARK_CHUNK_ID in chunk_ids


@pytest.mark.corpus
def test_benchmark_carp_multi_constraint(corpus_client):
    r = corpus_client.post(
        "/search",
        json={
            "query": BENCHMARK_QUERIES["carp"],
            "workspace_id": WORKSPACE_ID,
            "retrieval_mode": "multi_constraint",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "MULTI_CONSTRAINT"
    assert not data["refused"]
    assert data["bundles"]
    pages = {b["page_start"] for b in data["bundles"]}
    assert BENCHMARK_PAGE in pages
    assert BENCHMARK_CHUNK_ID in [h["chunk_id"] for h in data["hits"]]


def test_planner_extracts_amount_and_plaintiff():
    result = plan_query(
        "case context for supreme court with plaintiff damages of £1,000",
        retrieval_mode="multi_constraint",
    )
    types = {c.type for c in result.constraints}
    assert "amount" in types
    assert "party" in types
    assert result.mode == "MULTI_CONSTRAINT"
