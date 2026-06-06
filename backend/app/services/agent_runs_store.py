"""Persistence for agent mode SSE runs."""

from __future__ import annotations

import json
import uuid

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AgentRun
from app.db.session import utc_now_iso


def create_agent_run(
    db: Session,
    *,
    workspace_id: str,
    session_id: str | None,
) -> AgentRun:
    now = utc_now_iso()
    row = AgentRun(
        id=str(uuid.uuid4()),
        session_id=session_id,
        workspace_id=workspace_id,
        profile=settings.agent_profile,
        mode="agent",
        status="running",
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def append_events(db: Session, run_id: str, events: list[dict]) -> None:
    row = db.get(AgentRun, run_id)
    if not row:
        return
    existing: list[dict] = []
    if row.events_json:
        try:
            existing = json.loads(row.events_json)
        except json.JSONDecodeError:
            existing = []
    existing.extend(events)
    row.events_json = json.dumps(existing)
    row.updated_at = utc_now_iso()
    db.commit()


def finish_agent_run(
    db: Session,
    run_id: str,
    *,
    status: str,
    plan_json: dict | None = None,
) -> None:
    row = db.get(AgentRun, run_id)
    if not row:
        return
    row.status = status
    if plan_json is not None:
        row.plan_json = json.dumps(plan_json)
    row.updated_at = utc_now_iso()
    db.commit()


def get_agent_run(db: Session, run_id: str) -> AgentRun:
    row = db.get(AgentRun, run_id)
    if not row:
        raise ValueError("Agent run not found")
    return row


def agent_run_to_dict(row: AgentRun) -> dict:
    events: list[dict] = []
    if row.events_json:
        try:
            events = json.loads(row.events_json)
        except json.JSONDecodeError:
            events = []
    plan = None
    if row.plan_json:
        try:
            plan = json.loads(row.plan_json)
        except json.JSONDecodeError:
            plan = None
    return {
        "id": row.id,
        "session_id": row.session_id,
        "workspace_id": row.workspace_id,
        "profile": row.profile,
        "mode": row.mode,
        "plan_json": plan,
        "events": events,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
