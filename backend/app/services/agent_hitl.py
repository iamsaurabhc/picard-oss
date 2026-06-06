"""In-process HITL approval state for Agent mode (§4.3)."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PendingApproval:
    token: str
    kind: str  # scope | plan
    payload: dict[str, Any]
    session_id: str


_pending: dict[str, PendingApproval] = {}


def create_approval(*, session_id: str, kind: str, payload: dict[str, Any]) -> str:
    token = secrets.token_urlsafe(16)
    _pending[token] = PendingApproval(
        token=token,
        kind=kind,
        payload=payload,
        session_id=session_id,
    )
    return token


def consume_approval(token: str | None, session_id: str) -> PendingApproval | None:
    if not token:
        return None
    pending = _pending.pop(token, None)
    if not pending or pending.session_id != session_id:
        return None
    return pending


def scope_hitl_required(doc_count: int, profile: str) -> bool:
    from app.config import settings

    if settings.agent_skip_scope_hitl:
        return False
    if doc_count < settings.agent_scope_confirm_min_docs:
        return False
    if profile == "court":
        return True
    return doc_count >= settings.agent_scope_confirm_min_docs


def plan_hitl_required(profile: str) -> bool:
    return profile == "court"
