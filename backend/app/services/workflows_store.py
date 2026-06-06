from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import HiddenWorkflow, Workflow
from app.db.session import utc_now_iso
from app.workflows.builtins import builtin_workflow_defs
from app.workflows.schema import ValidationResult, WorkflowPayload
from app.workflows.validate import validate_workflow_record


def _json_dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _parse_json(raw: str | None) -> Any:
    if not raw:
        return None
    return json.loads(raw)


def workflow_matches_profile(workflow_profile: str, agent_profile: str) -> bool:
    if workflow_profile == "any":
        return True
    return workflow_profile == agent_profile


def seed_builtin_workflows(db: Session) -> int:
    existing = db.scalar(
        select(Workflow.id).where(Workflow.is_builtin == 1).limit(1)
    )
    if existing:
        return 0
    now = utc_now_iso()
    count = 0
    for row in builtin_workflow_defs():
        cols = row.get("columns_config_json")
        inp = row.get("input_schema_json")
        ep = row["evidence_profile_json"]
        fj = row["flow_json"]
        wf = Workflow(
            id=row["id"],
            workspace_id=row.get("workspace_id"),
            type=row["type"],
            title=row["title"],
            practice_area=row.get("practice_area"),
            prompt_md=row.get("prompt_md"),
            columns_config_json=_json_dump(cols) if cols else None,
            flow_json=_json_dump(fj),
            flow_version=row.get("flow_version", "lightflow-0.8"),
            input_schema_json=_json_dump(inp) if inp else None,
            evidence_profile_json=_json_dump(ep),
            profile=row.get("profile", "any"),
            source=row.get("source", "builtin"),
            requires_approval=1 if row.get("requires_approval") else 0,
            is_builtin=1,
            created_at=now,
            updated_at=now,
        )
        db.add(wf)
        count += 1
    return count


def _workflow_to_dict(wf: Workflow) -> dict[str, Any]:
    return {
        "id": wf.id,
        "workspace_id": wf.workspace_id,
        "type": wf.type,
        "title": wf.title,
        "practice_area": wf.practice_area,
        "prompt_md": wf.prompt_md,
        "columns_config": _parse_json(wf.columns_config_json),
        "flow_json": _parse_json(wf.flow_json),
        "flow_version": wf.flow_version,
        "input_schema": _parse_json(wf.input_schema_json),
        "evidence_profile": _parse_json(wf.evidence_profile_json),
        "profile": wf.profile,
        "source": wf.source,
        "requires_approval": bool(wf.requires_approval),
        "is_builtin": bool(wf.is_builtin),
        "created_at": wf.created_at,
        "updated_at": wf.updated_at,
    }


def get_workflow(db: Session, workflow_id: str) -> Workflow:
    wf = db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf


def list_workflows(
    db: Session,
    *,
    workspace_id: str | None = None,
    type_filter: str | None = None,
    practice_area: str | None = None,
    agent_profile: str | None = None,
    include_hidden: bool = False,
) -> list[dict[str, Any]]:
    profile = agent_profile or getattr(settings, "agent_profile", "firm")
    hidden_ids: set[str] = set()
    if not include_hidden:
        hidden_ids = {
            row.workflow_id
            for row in db.scalars(select(HiddenWorkflow.workflow_id)).all()
        }

    q = select(Workflow).where(
        or_(Workflow.workspace_id.is_(None), Workflow.workspace_id == workspace_id)
    )
    if type_filter:
        q = q.where(Workflow.type == type_filter)
    if practice_area:
        q = q.where(Workflow.practice_area == practice_area)

    rows = db.scalars(q.order_by(Workflow.title)).all()
    out: list[dict[str, Any]] = []
    for wf in rows:
        if wf.id in hidden_ids:
            continue
        if not workflow_matches_profile(wf.profile, profile):
            continue
        out.append(_workflow_to_dict(wf))
    return out


def create_workflow(
    db: Session,
    body: WorkflowPayload,
    *,
    source: str = "user",
) -> dict[str, Any]:
    validation = validate_workflow_record(
        flow_json=body.flow_json.model_dump(),
        evidence_profile_json=body.evidence_profile.model_dump(),
    )
    if not validation.valid:
        raise HTTPException(status_code=400, detail=_validation_errors(validation))

    now = utc_now_iso()
    wf_id = f"user:{uuid.uuid4()}"
    wf = Workflow(
        id=wf_id,
        workspace_id=body.workspace_id,
        type=body.type,
        title=body.title,
        practice_area=body.practice_area,
        prompt_md=body.prompt_md,
        columns_config_json=_json_dump(body.columns_config) if body.columns_config else None,
        flow_json=_json_dump(body.flow_json.model_dump()),
        flow_version="lightflow-0.8",
        input_schema_json=_json_dump(body.input_schema) if body.input_schema else None,
        evidence_profile_json=_json_dump(body.evidence_profile.model_dump()),
        profile=body.profile,
        source=source,
        requires_approval=1 if body.requires_approval else 0,
        is_builtin=0,
        created_at=now,
        updated_at=now,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return _workflow_to_dict(wf)


def update_workflow(db: Session, workflow_id: str, body: WorkflowPayload) -> dict[str, Any]:
    wf = get_workflow(db, workflow_id)
    if wf.is_builtin:
        raise HTTPException(status_code=403, detail="Cannot modify built-in workflow")
    validation = validate_workflow_record(
        flow_json=body.flow_json.model_dump(),
        evidence_profile_json=body.evidence_profile.model_dump(),
    )
    if not validation.valid:
        raise HTTPException(status_code=400, detail=_validation_errors(validation))

    wf.type = body.type
    wf.title = body.title
    wf.practice_area = body.practice_area
    wf.prompt_md = body.prompt_md
    wf.columns_config_json = _json_dump(body.columns_config) if body.columns_config else None
    wf.flow_json = _json_dump(body.flow_json.model_dump())
    wf.input_schema_json = _json_dump(body.input_schema) if body.input_schema else None
    wf.evidence_profile_json = _json_dump(body.evidence_profile.model_dump())
    wf.profile = body.profile
    wf.requires_approval = 1 if body.requires_approval else 0
    wf.updated_at = utc_now_iso()
    db.commit()
    db.refresh(wf)
    return _workflow_to_dict(wf)


def hide_workflow(db: Session, workflow_id: str) -> None:
    wf = get_workflow(db, workflow_id)
    if not wf.is_builtin:
        raise HTTPException(status_code=400, detail="Only built-in workflows can be hidden")
    existing = db.get(HiddenWorkflow, workflow_id)
    if existing:
        return
    db.add(HiddenWorkflow(workflow_id=workflow_id, created_at=utc_now_iso()))
    db.commit()


def export_workflow(db: Session, workflow_id: str) -> dict[str, Any]:
    return _workflow_to_dict(get_workflow(db, workflow_id))


def validate_workflow_by_id(db: Session, workflow_id: str) -> ValidationResult:
    wf = get_workflow(db, workflow_id)
    return validate_workflow_record(
        flow_json=wf.flow_json,
        evidence_profile_json=wf.evidence_profile_json,
    )


def validate_payload(body: WorkflowPayload) -> ValidationResult:
    return validate_workflow_record(
        flow_json=body.flow_json.model_dump(),
        evidence_profile_json=body.evidence_profile.model_dump(),
    )


def _validation_errors(result: ValidationResult) -> list[dict[str, str]]:
    return [{"code": i.code, "message": i.message, "step": i.step} for i in result.errors]


def get_workflow_allowed_intents(wf: Workflow) -> list[str] | None:
    profile = _parse_json(wf.evidence_profile_json)
    if not profile:
        return None
    intents = profile.get("allowed_intents")
    return intents if intents else None


def get_workflow_intent_hint(wf: Workflow) -> str | None:
    """When a workflow pins a single CARP intent, return it for query understanding (WF-01)."""
    intents = get_workflow_allowed_intents(wf)
    if intents and len(intents) == 1:
        return intents[0]
    return None


def apply_workflow_intent_hint(understanding, hint: str | None, allowed_intents: list[str] | None):
    """Constrain planner intent after understand_query (WF-01)."""
    if hint:
        understanding.intent = hint
        return understanding
    if allowed_intents and understanding.intent not in allowed_intents:
        understanding.intent = allowed_intents[0]
    return understanding


def workflow_prompt_prefix(wf: Workflow) -> str | None:
    if not wf.prompt_md:
        return None
    return wf.prompt_md.strip()


def workflow_message_marker(wf: Workflow) -> str:
    return f"[Workflow: {wf.title} ({wf.id})]"
