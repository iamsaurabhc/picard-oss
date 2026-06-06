from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.schemas import ChatStreamRequest


@dataclass
class ToolContext:
    db: Session
    workspace_id: str
    session_id: str
    document_ids: list[str] | None = None
    profile: str = "firm"
    emit_sse: Callable[[dict], None] | None = None
    approval_token: str | None = None
    pending_plan_json: dict | None = None
    plan_approved: bool = False
    scope_approved: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def stream_request(self, message: str) -> ChatStreamRequest:
        return ChatStreamRequest(
            session_id=self.session_id,
            workspace_id=self.workspace_id,
            message=message,
            mode="agent",
            document_ids=self.document_ids,
        )

    def emit(self, payload: dict) -> None:
        if self.emit_sse:
            self.emit_sse(payload)
