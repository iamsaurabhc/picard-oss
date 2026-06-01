from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.db.session import get_db
from app.schemas import ChatMessageOut, ChatSessionCreate, ChatSessionOut, ChatStreamRequest
from app.services.chat import create_session, list_messages, stream_chat

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/sessions", response_model=ChatSessionOut)
def post_session(body: ChatSessionCreate, db: Session = Depends(get_db)):
    session = create_session(db, body.workspace_id, body.title)
    return session


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
