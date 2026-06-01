import json
from unittest.mock import patch

from app.config import settings
from app.schemas import SearchHit
from app.services.context_ranker import rank_context
from app.services.query_understanding import QueryUnderstanding


def _hit(chunk_id: str, text: str, page: int = 1) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        document_id="d1",
        page_number=page,
        text_content=text,
        heading_path=None,
        score=1.0,
    )


def test_rank_context_fallback_filters_short():
    settings.enable_context_ranker = False
    hits = [
        _hit("short", "WAVERLEY"),
        _hit("long", "The plaintiff claimed damages in the sum of £1,000 for negligence."),
    ]
    u = QueryUnderstanding()
    ranked, diag = rank_context("damages claimed", u, hits, top_k=2)
    assert len(ranked) == 1
    assert ranked[0].chunk_id == "long"
    assert diag["fallback"] == "bm25_informative"


def test_rank_context_llm_order():
    settings.enable_context_ranker = True
    hits = [
        _hit("c1", "Header only WAVERLEY", page=2),
        _hit("c2", "The plaintiff claimed damages in the sum of £1,000.", page=3),
    ]
    payload = {"ranked_chunk_ids": ["c2", "c1"], "dropped": [{"chunk_id": "c1", "reason": "header"}]}
    with patch("app.services.context_ranker.completion", return_value=json.dumps(payload)):
        ranked, diag = rank_context("What damages did the plaintiff claim?", QueryUnderstanding(), hits, top_k=2)
    assert ranked[0].chunk_id == "c2"
    assert diag["used_llm"] is True
