import pytest

from app.services.fts_search import fts_search
from tests.corpus_constants import DOCUMENT_ID, SIMPLE_QUERIES, WORKSPACE_ID


@pytest.mark.corpus
def test_fts_liability_hits(corpus_session):
    hits = fts_search(
        corpus_session,
        query="liability",
        workspace_id=WORKSPACE_ID,
        document_ids=[DOCUMENT_ID],
        top_k=10,
    )
    assert len(hits) >= SIMPLE_QUERIES["liability"]["min_hits"]
    assert all(h.document_id == DOCUMENT_ID for h in hits)
    assert all(h.bbox_json for h in hits)


@pytest.mark.corpus
def test_fts_bbox_present(corpus_session):
    hits = fts_search(corpus_session, query="negligence", workspace_id=WORKSPACE_ID, top_k=5)
    assert hits
    for hit in hits:
        assert hit.bbox_json


@pytest.mark.corpus
def test_fts_benchmark_line(corpus_session):
    hits = fts_search(
        corpus_session,
        query="plaintiff claimed damages",
        workspace_id=WORKSPACE_ID,
        document_ids=[DOCUMENT_ID],
        top_k=5,
    )
    from tests.corpus_constants import BENCHMARK_CHUNK_ID, BENCHMARK_LINE

    assert hits
    assert any(h.chunk_id == BENCHMARK_CHUNK_ID for h in hits)
    assert any(BENCHMARK_LINE in h.text_content for h in hits)


@pytest.mark.corpus
def test_fts_workspace_scoping(corpus_session):
    hits = fts_search(corpus_session, query="liability", workspace_id="nonexistent-workspace", top_k=5)
    assert hits == []
