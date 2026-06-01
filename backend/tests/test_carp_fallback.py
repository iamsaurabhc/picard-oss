import pytest
from unittest.mock import MagicMock, patch

from app.config import settings
from app.schemas import SearchHit, SearchRequest
from app.services.search import execute_search


@pytest.fixture()
def mock_db():
    return MagicMock()


def test_carp_refuse_falls_back_to_planned(mock_db):
    settings.enable_carp = True
    settings.enable_llm_query_understanding = False

    carp_result = MagicMock()
    carp_result.refused = True
    carp_result.chunks = []
    carp_result.bundles = []
    carp_result.proximity_tier_used = None
    carp_result.retrieval_diagnostics = {"intersection_pages": 0}
    carp_result.suggestions = ["Try broader terms."]

    mock_hit = SearchHit(
        chunk_id="chunk-1",
        document_id="doc-1",
        page_number=3,
        text_content="Plaintiff claimed damages in the sum of £1,000.",
        heading_path=None,
        score=1.0,
    )

    with (
        patch("app.services.search._validate_scope", return_value=None),
        patch("app.services.search.filter_documents_by_metadata", return_value=None),
        patch("app.services.search.run_carp", return_value=carp_result),
        patch(
            "app.services.search.planned_retrieve",
            return_value=([mock_hit], {"anchor_fts": "damages claimed", "passes": ["anchor:1"]}),
        ) as mock_planned,
    ):
        body = SearchRequest(
            query="case context for supreme court and agreement that",
            workspace_id="ws-1",
            retrieval_mode="multi_constraint",
            top_k=10,
        )
        result = execute_search(mock_db, body)

    assert result.refused is False
    assert result.mode == "SIMPLE"
    assert len(result.hits) == 1
    assert mock_planned.called
    path = result.retrieval_diagnostics.get("retrieval_path", [])
    assert "planned_fallback" in path


def test_factual_lookup_skips_carp(mock_db):
    settings.enable_carp = True
    settings.enable_llm_query_understanding = False

    mock_hit = SearchHit(
        chunk_id="chunk-1",
        document_id="doc-1",
        page_number=3,
        text_content="Damages claimed £1,000.",
        heading_path=None,
        score=1.0,
    )

    with (
        patch("app.services.search._validate_scope", return_value=None),
        patch("app.services.search.filter_documents_by_metadata", return_value=None),
        patch("app.services.search.run_carp") as mock_carp,
        patch(
            "app.services.search.planned_retrieve",
            return_value=([mock_hit], {"anchor_fts": "damages claimed", "passes": ["pinpoint_fact:1"]}),
        ),
    ):
        body = SearchRequest(
            query="amount claimed by janet chester?",
            workspace_id="ws-1",
            top_k=10,
        )
        result = execute_search(mock_db, body)

    mock_carp.assert_not_called()
    assert result.mode == "SIMPLE"
    assert not result.refused
