import pytest

from app.schemas import SearchRequest
from app.services.search import execute_search
from tests.corpus_constants import DOCUMENT_ID, WORKSPACE_ID


@pytest.mark.corpus
def test_search_api_simple(corpus_client):
    r = corpus_client.post(
        "/search",
        json={"query": "liability", "workspace_id": WORKSPACE_ID, "retrieval_mode": "simple"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "SIMPLE"
    assert len(data["hits"]) >= 1
    assert data["hits"][0]["bbox"] is not None


@pytest.mark.corpus
def test_search_requires_workspace(corpus_client):
    r = corpus_client.post("/search", json={"query": "test", "workspace_id": WORKSPACE_ID})
    assert r.status_code == 200


@pytest.mark.corpus
def test_eval_gates_drm(corpus_session):
    from app.services.fts_search import fts_search

    hits = fts_search(
        corpus_session,
        query="liability",
        workspace_id=WORKSPACE_ID,
        document_ids=[DOCUMENT_ID],
        top_k=10,
    )
    assert hits
    assert hits[0].document_id == DOCUMENT_ID
