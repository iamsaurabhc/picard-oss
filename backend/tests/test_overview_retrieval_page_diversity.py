import pytest

from app.config import settings
from app.services.overview_retrieval import overview_retrieve
from app.services.query_understanding import understand_query
from tests.corpus_constants import BENCHMARK_CHUNK_ID, BENCHMARK_LINE, BENCHMARK_PAGE, DOCUMENT_ID, WORKSPACE_ID


@pytest.mark.corpus
def test_overview_retrieval_hits_damages_and_early_pages(corpus_session):
    settings.enable_llm_query_understanding = False
    query = "List all case details involving Chester v Waverley"
    u = understand_query(query)
    assert u.intent == "case_overview"

    hits, diag = overview_retrieve(
        corpus_session,
        u,
        workspace_id=WORKSPACE_ID,
        document_ids=[DOCUMENT_ID],
        query=query,
    )
    assert diag["retrieval_strategy"] == "case_overview"
    min_pages = 2 if diag.get("strategy") == "overview_page_context" else 3
    assert diag["distinct_pages"] >= min_pages

    pages = {h.page_number for h in hits}
    assert 2 in pages or 3 in pages
    chunk_ids = {h.chunk_id for h in hits}
    damages_on_page = any(
        h.page_number == BENCHMARK_PAGE and BENCHMARK_LINE in (h.text_content or "")
        for h in hits
    )
    assert damages_on_page or BENCHMARK_CHUNK_ID in chunk_ids
