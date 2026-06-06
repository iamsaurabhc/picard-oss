"""LightAgent runtime bridge for POST /chat/stream mode=agent (kernel-first)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ChatMessage
from app.schemas import ChatStreamRequest
from app.services.agent_hitl import consume_approval
from app.services.agent_memory import PicardMemory, mem0_user_id, memory_store_allowed
from app.services.agent_pack import agent_pack_available, agent_pack_error
from app.services.agent_runs_store import append_events, create_agent_run, finish_agent_run
from app.services.chat import stream_chat
from app.services.model_router import llm_available
from app.db.models import ChatSession
from app.tools.context import ToolContext

logger = logging.getLogger(__name__)


async def stream_agent_run(db: Session, body: ChatStreamRequest) -> AsyncIterator[dict]:
    """
    Agent mode: kernel-first corpus Q&A (same stream as Chat with mode=agent).

    LightAgent tool loop is not used for vault Q&A — Citation Kernel streams cited
    markdown + references in one pass. Vault/workflow tools remain on ToolContext for
    workflow execution paths.
    """
    if not settings.enable_agent_mode:
        yield {"event": "error", "message": "Agent mode is disabled. Enable it in Settings."}
        return
    if not llm_available():
        yield {"event": "error", "message": "LLM is not configured."}
        return
    if not agent_pack_available():
        yield {"event": "error", "message": agent_pack_error() or "Agent pack not installed."}
        return

    session = db.get(ChatSession, body.session_id)
    if not session:
        yield {"event": "error", "message": "Session not found"}
        return

    profile = settings.agent_profile
    user_id = mem0_user_id(body.workspace_id, profile)
    picard_memory = PicardMemory(db)

    run = create_agent_run(db, workspace_id=body.workspace_id, session_id=body.session_id)
    events_log: list[dict] = []

    ctx = ToolContext(
        db=db,
        workspace_id=body.workspace_id,
        session_id=body.session_id,
        document_ids=body.document_ids,
        profile=profile,
        emit_sse=events_log.append,
    )

    if body.approval_token:
        pending = consume_approval(body.approval_token, body.session_id)
        if pending:
            if pending.kind == "scope":
                ctx.scope_approved = True
                ctx.document_ids = pending.payload.get("document_ids")
                body = body.model_copy(update={"document_ids": ctx.document_ids})
            elif pending.kind == "plan":
                ctx.plan_approved = True
                ctx.pending_plan_json = pending.payload.get("flow_json")

    memory_hits = picard_memory.retrieve(body.message, user_id)
    if memory_hits:
        payload = {"event": "memory_hit", "memories": memory_hits}
        events_log.append(payload)
        yield payload

    agent_body = body if body.mode == "agent" else body.model_copy(update={"mode": "agent"})

    try:
        async for ev in stream_chat(db, agent_body):
            events_log.append(ev)
            yield ev
    except Exception as exc:
        logger.exception("agent kernel stream failed")
        err = {"event": "error", "message": str(exc)}
        events_log.append(err)
        yield err
        finish_agent_run(db, run.id, status="error")
        append_events(db, run.id, events_log)
        return

    if settings.mem0_store_on_run_end:
        last = db.scalar(
            select(ChatMessage)
            .where(ChatMessage.session_id == body.session_id, ChatMessage.role == "assistant")
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        if last and last.content and memory_store_allowed(last.content):
            summary = f"Agent session note: {last.content[:500]}"
            if memory_store_allowed(summary):
                picard_memory.store(summary, user_id)

    finish_agent_run(db, run.id, status="completed", plan_json=ctx.pending_plan_json)
    append_events(db, run.id, events_log)
