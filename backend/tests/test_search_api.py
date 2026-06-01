import pytest

from app.schemas import SearchRequest
from app.services.search import execute_search
from tests.corpus_constants import WORKSPACE_ID


@pytest.mark.corpus
def test_search_api_auto_route(corpus_client):
    r = corpus_client.post(
        "/search",
        json={"query": "liability", "workspace_id": WORKSPACE_ID},
    )
    assert r.status_code == 200
    assert r.json()["mode"] in ("SIMPLE", "MULTI_CONSTRAINT")


@pytest.mark.corpus
def test_search_carp_route(corpus_client):
    r = corpus_client.post(
        "/search",
        json={
            "query": "case context for supreme court and refused",
            "workspace_id": WORKSPACE_ID,
            "retrieval_mode": "multi_constraint",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "MULTI_CONSTRAINT"
