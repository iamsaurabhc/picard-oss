import pytest

from app.config import settings
from app.services.citations import build_citation_map, build_system_prompt
from app.services.context_ranker import rank_context
from app.services.planned_retrieval import PlannedRetrievalConfig, planned_retrieve
from app.services.query_understanding import understand_query
from tests.corpus_constants import DOCUMENT_ID, WORKSPACE_ID


@pytest.mark.corpus
def test_compound_factual_retrieves_hits(corpus_session):
    settings.enable_llm_query_understanding = False
    settings.enable_excerpt_selector = False
    query = "janet chester son's name? age? date of accident?"
    u = understand_query(
        query,
        db=corpus_session,
        workspace_id=WORKSPACE_ID,
        document_ids=[DOCUMENT_ID],
    )
    assert u.intent == "factual_lookup"
    assert len(u.search_passes) >= 1

    hits, diag = planned_retrieve(
        corpus_session,
        u,
        workspace_id=WORKSPACE_ID,
        document_ids=[DOCUMENT_ID],
        query=query,
        config=PlannedRetrievalConfig(pool_k=24, max_per_page=4, strategy="planned"),
    )
    assert len(hits) > 0
    assert diag["pool_size"] > 0


@pytest.mark.corpus
def test_compound_factual_prompt_with_sub_questions(corpus_session):
    settings.enable_llm_query_understanding = False
    settings.enable_context_ranker = False
    settings.enable_excerpt_selector = False
    query = "janet chester son's name? age? date of accident?"
    u = understand_query(
        query,
        db=corpus_session,
        workspace_id=WORKSPACE_ID,
        document_ids=[DOCUMENT_ID],
    )
    hits, _ = planned_retrieve(
        corpus_session,
        u,
        workspace_id=WORKSPACE_ID,
        document_ids=[DOCUMENT_ID],
        query=query,
        config=PlannedRetrievalConfig(pool_k=24, max_per_page=4, strategy="planned"),
    )
    ranked, _ = rank_context(query, u, hits, top_k=12, rank_mode="precision")
    cmap = build_citation_map(
        ranked,
        excerpt_chars=600,
        question=query,
        sub_questions=u.sub_questions,
    )
    prompt = build_system_prompt(cmap, intent="factual_lookup", sub_questions=u.sub_questions)
    assert "Excerpt:" in prompt
    assert len(cmap.refs) > 0
    joined = " ".join(r.preview for r in cmap.refs).casefold()
    assert "infant son" in joined
    assert "ma x" in joined or "chester" in joined
