"""Agent kernel-first runtime tests."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from app.schemas import ChatStreamRequest
from app.services import lightagent_runtime as la


async def _collect(gen):
    return [e async for e in gen]


def _run_agent_stream(db, body, fake_stream):
    with (
        patch.object(la.settings, "enable_agent_mode", True),
        patch.object(la.settings, "agent_profile", "firm"),
        patch.object(la.settings, "mem0_store_on_run_end", False),
        patch.object(la, "agent_pack_available", return_value=True),
        patch.object(la, "llm_available", return_value=True),
        patch.object(la, "create_agent_run", return_value=MagicMock(id="run-1")),
        patch.object(la, "stream_chat", fake_stream),
        patch.object(la, "append_events"),
        patch.object(la, "finish_agent_run"),
        patch.object(la, "_persist_message"),
        patch.object(la, "_touch_session_after_user_turn"),
        patch.object(la, "PicardMemory") as mock_mem,
    ):
        mock_mem.return_value.retrieve.return_value = []
        db.get.return_value = MagicMock()
        return asyncio.run(_collect(la.stream_agent_run(db, body)))


def test_agent_kernel_first_delegates_to_stream_chat():
    body = ChatStreamRequest(
        session_id="s1",
        workspace_id="ws1",
        message="list all cases against Google",
        mode="agent",
    )

    async def fake_stream(_db, _body):
        yield {"event": "progress", "phase": "understanding", "status": "start"}
        yield {"event": "content", "delta": "Answer [1]."}
        yield {
            "event": "references",
            "references": [{"index": 1, "chunk_id": "c1", "page": 1}],
        }
        yield {"event": "done"}

    events = _run_agent_stream(MagicMock(), body, fake_stream)
    types = [e["event"] for e in events]
    assert "content" in types
    assert "references" in types
    assert types[-1] == "done"
    assert "tool_call" not in types


def test_agent_no_double_corpus_tool_loop():
    body = ChatStreamRequest(session_id="s1", workspace_id="ws1", message="What is the cap?", mode="agent")

    async def fake_stream(_db, _body):
        yield {"event": "content", "delta": "Cap [1]."}
        yield {"event": "references", "references": [{"index": 1}]}
        yield {"event": "done"}

    _run_agent_stream(MagicMock(), body, fake_stream)
