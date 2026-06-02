from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.db.session import get_db
from app.schemas import (
    ChatMessageOut,
    ChatSessionCreate,
    ChatSessionOut,
    ChatSessionSummary,
    ChatSessionUpdate,
    ChatStreamRequest,
)
from app.services.chat import (
    create_session,
    delete_session,
    get_or_create_draft_session,
    get_session,
    list_messages,
    list_sessions,
    session_to_out,
    stream_chat,
    update_session,
)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/sessions", response_model=ChatSessionOut)
def post_session(body: ChatSessionCreate, db: Session = Depends(get_db)):
    if body.reuse_draft:
        session = get_or_create_draft_session(db, body.workspace_id, body.title)
    else:
        session = create_session(db, body.workspace_id, body.title)
    return session_to_out(session)


@router.get("/sessions/{session_id}", response_model=ChatSessionOut)
def get_session_route(session_id: str, db: Session = Depends(get_db)):
    try:
        return get_session(db, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/sessions/{session_id}", response_model=ChatSessionOut)
def patch_session(session_id: str, body: ChatSessionUpdate, db: Session = Depends(get_db)):
    try:
        return update_session(db, session_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session_route(session_id: str, db: Session = Depends(get_db)):
    try:
        delete_session(db, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageOut])
def get_messages(session_id: str, db: Session = Depends(get_db)):
    messages = list_messages(db, session_id)
    out: list[ChatMessageOut] = []
    for m in messages:
        refs = json.loads(m.references_json) if m.references_json else None
        out.append(
            ChatMessageOut(
                id=m.id,
                session_id=m.session_id,
                role=m.role,
                content=m.content,
                references=refs,
                refused=bool(m.refused),
                created_at=m.created_at,
            )
        )
    return out


@router.post("/stream")
async def chat_stream(body: ChatStreamRequest, db: Session = Depends(get_db)):
    if not settings.enable_chat:
        raise HTTPException(status_code=503, detail="Chat is disabled")

    async def event_generator():
        try:
            async for payload in stream_chat(db, body):
                event = payload.pop("event")
                yield {"event": event, "data": json.dumps(payload)}
        except ValueError as exc:
            yield {"event": "error", "data": json.dumps({"detail": str(exc)})}

    return EventSourceResponse(event_generator())
