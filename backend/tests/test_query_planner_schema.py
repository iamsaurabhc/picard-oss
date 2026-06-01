import json
from unittest.mock import patch

from app.config import settings
from app.services.document_context import DocumentContext, build_document_context
from app.services.query_understanding import _sanitize_fts_terms, understand_query


def test_sanitize_fts_terms_strips_possessives_and_search_words():
    assert _sanitize_fts_terms(["plaintiff's son search"]) == ["plaintiff", "son"]
    assert _sanitize_fts_terms(["son's age"]) == ["son", "age"]
    assert _sanitize_fts_terms(["what", "name"]) == []


def test_document_context_prompt_block_empty():
    ctx = DocumentContext()
    block = ctx.to_prompt_block()
    assert "No indexed metadata" in block


def test_query_planner_uses_document_context_in_prompt():
    settings.enable_llm_query_understanding = True
    settings.query_planner_repair_on_zero_hits = False
    captured: list[str] = []

    def fake_completion(*, messages, **kwargs):
        captured.append(messages[0]["content"])
        return json.dumps({
            "retrieval_mode": "SIMPLE",
            "intent": "general",
            "constraints": [],
            "fts": {"must_terms": ["alpha", "beta"], "should_terms": [], "phrases": [], "operator": "AND"},
            "search_passes": [{"label": "main", "fts_terms": ["alpha", "beta"], "pin_best": False}],
            "confidence": 0.9,
        })

    ctx = DocumentContext(doc_type="litigation", parties=["Alpha Corp"], page_previews=["Sample contract text"])
    with patch("app.services.query_understanding.completion", side_effect=fake_completion):
        with patch("app.services.query_understanding.build_document_context", return_value=ctx):
            u = understand_query("alpha beta terms?", db=object(), workspace_id="ws", document_ids=["d1"])
    assert u.used_llm
    assert "Alpha Corp" in captured[0]
    assert "litigation" in captured[0]
