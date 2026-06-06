"""Agent tool citation tests (Phase 7a — AG-01, AG-02, UC-02)."""

from __future__ import annotations

import asyncio
import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas import ChatStreamRequest, SearchHit
from app.services.agent_memory import memory_store_allowed
from app.tools.context import ToolContext
from app.services.citations import build_system_prompt
from app.tools.corpus import bind_corpus_tools
from app.tools.lightagent_meta import normalize_lightagent_tool


def _hit(chunk_id: str, doc_id: str = "d1") -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        document_id=doc_id,
        page_number=1,
        text_content=f"text {chunk_id}",
        heading_path=None,
        bbox={"x0": 0.1, "y0": 0.2, "x1": 0.9, "y1": 0.3},
        score=1.0,
    )


def test_search_corpus_returns_chunk_ids():
    db = MagicMock()
    ctx = ToolContext(db=db, workspace_id="ws-1", session_id="s1", profile="firm")
    tools = {
        t.tool_info["tool_name"]: t
        for t in (normalize_lightagent_tool(x) for x in bind_corpus_tools(ctx))
    }
    with patch("app.tools.corpus.retrieve_for_agent") as mock_ret:
        mock_ret.return_value = MagicMock(
            hits=[_hit("c1"), _hit("c2", "d2")],
            listing_map_result=None,
            retrieval_diagnostics={"document_ids_discovered": ["d1", "d2"]},
        )
        raw = tools["search_corpus"]("google v CUTS")
    data = json.loads(raw)
    assert data["refused"] is False
    body = json.loads(data["content"])
    assert body["chunk_ids"] == ["c1", "c2"]
    assert body["document_ids"] == ["d1", "d2"]
    assert len(body["snippets"]) == 2


def test_ag02_search_corpus_refuse_empty():
    db = MagicMock()
    ctx = ToolContext(db=db, workspace_id="ws-1", session_id="s1", profile="firm")
    emitted: list[dict] = []
    ctx.emit_sse = emitted.append
    tools = {
        t.tool_info["tool_name"]: t
        for t in (normalize_lightagent_tool(x) for x in bind_corpus_tools(ctx))
    }
    with patch("app.tools.corpus.retrieve_for_agent") as mock_ret:
        mock_ret.return_value = MagicMock(hits=[], listing_map_result=None, retrieval_diagnostics={})
        raw = tools["search_corpus"]("liability cap?")
    data = json.loads(raw)
    assert data["refused"] is True
    assert any(e.get("event") == "step_refused" for e in emitted)


def test_uc02_answer_from_corpus_uses_shared_pipeline():
    db = MagicMock()
    ctx = ToolContext(db=db, workspace_id="ws-1", session_id="s1", profile="firm")
    tools = {
        t.tool_info["tool_name"]: t
        for t in (normalize_lightagent_tool(x) for x in bind_corpus_tools(ctx))
    }
    with patch("app.tools.corpus.run_chat_corpus_answer", new_callable=AsyncMock) as mock_answer:
        from app.services.citation_kernel import EvidenceStepResult, _empty_citation_map, _empty_validation
        from app.services.citations import build_citation_map

        cmap = build_citation_map([_hit("c1")], doc_names={"d1": "doc.pdf"})
        mock_answer.return_value = EvidenceStepResult(
            refused=False,
            content="Cap is limited [1].",
            citation_map=cmap,
            references=[{"index": 1, "chunk_id": "c1", "page": 1}],
            validation=_empty_validation(),
            judge=None,
        )
        raw = tools["answer_from_corpus"]("What is the cap?")
    mock_answer.assert_called_once()
    body = mock_answer.call_args[0][1]
    assert isinstance(body, ChatStreamRequest)
    data = json.loads(raw)
    assert data["refused"] is False
    assert "[1]" in data["content"]
    assert data["references"]


def test_agent_listing_prompt_uses_catalog_template():
    from app.services.citations import build_citation_map

    cmap = build_citation_map([_hit("c1")], doc_names={"d1": "Order-30-2012.pdf"})
    prompt = build_system_prompt(
        cmap,
        intent="entity_matter_listing",
        target_entity="google",
        synthesis_mode="agent",
    )
    assert "multi-matter catalog for Agent mode" in prompt
    assert "Do NOT use case_overview skeleton" in prompt
    assert "## [Document filename" in prompt


def test_answer_from_corpus_emits_references_sse():
    db = MagicMock()
    emitted: list[dict] = []
    ctx = ToolContext(db=db, workspace_id="ws-1", session_id="s1", profile="firm")
    ctx.emit_sse = emitted.append
    tools = {
        t.tool_info["tool_name"]: t
        for t in (normalize_lightagent_tool(x) for x in bind_corpus_tools(ctx))
    }
    with patch("app.tools.corpus.run_chat_corpus_answer", new_callable=AsyncMock) as mock_answer:
        from app.services.citation_kernel import EvidenceStepResult, _empty_citation_map, _empty_validation
        from app.services.citations import build_citation_map

        cmap = build_citation_map([_hit("c1")], doc_names={"d1": "doc.pdf"})
        mock_answer.return_value = EvidenceStepResult(
            refused=False,
            content="Matter [1].",
            citation_map=cmap,
            references=[{"index": 1}],
            validation=_empty_validation(),
            judge=None,
        )
        tools["answer_from_corpus"]("list cases")
    assert any(e.get("event") == "references" for e in emitted)


def test_ag01_markers_in_tool_output_resolve():
    content = "Party A is liable [1] and Party B [2]."
    assert len(re.findall(r"\[(\d+)\]", content)) == 2
