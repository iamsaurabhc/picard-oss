from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.schemas import WorkflowCreate, WorkflowOut, WorkflowValidationOut
from app.services import workflows_store as store
from app.workflows.schema import EvidenceProfile, FlowJson, ValidationIssue, WorkflowPayload

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _to_out(data: dict) -> WorkflowOut:
    return WorkflowOut(**data)


def _validation_out(result) -> WorkflowValidationOut:
    def issues(items: list[ValidationIssue]):
        return [
            {
                "level": i.level,
                "code": i.code,
                "message": i.message,
                "step": i.step,
            }
            for i in items
        ]

    return WorkflowValidationOut(
        valid=result.valid,
        errors=issues(result.errors),
        warnings=issues(result.warnings),
    )


def _body_to_payload(body: WorkflowCreate) -> WorkflowPayload:
    columns = None
    if body.columns_config:
        columns = [c.model_dump() for c in body.columns_config]
    return WorkflowPayload(
        workspace_id=body.workspace_id,
        type=body.type,
        title=body.title,
        practice_area=body.practice_area,
        prompt_md=body.prompt_md,
        columns_config=columns,
        flow_json=FlowJson.model_validate(body.flow_json),
        input_schema=body.input_schema,
        evidence_profile=EvidenceProfile.model_validate(body.evidence_profile),
        profile=body.profile,
        requires_approval=body.requires_approval,
    )


@router.get("", response_model=list[WorkflowOut])
def list_workflows(
    workspace_id: str | None = Query(None),
    type: str | None = Query(None, alias="type"),
    practice_area: str | None = Query(None),
    db: Session = Depends(get_db),
):
    rows = store.list_workflows(
        db,
        workspace_id=workspace_id,
        type_filter=type,
        practice_area=practice_area,
        agent_profile=settings.agent_profile,
    )
    return [_to_out(r) for r in rows]


@router.post("", response_model=WorkflowOut, status_code=201)
def create_workflow(body: WorkflowCreate, db: Session = Depends(get_db)):
    data = store.create_workflow(db, _body_to_payload(body))
    return _to_out(data)


@router.get("/{workflow_id}", response_model=WorkflowOut)
def get_workflow_route(workflow_id: str, db: Session = Depends(get_db)):
    return _to_out(store.export_workflow(db, workflow_id))


@router.patch("/{workflow_id}", response_model=WorkflowOut)
def patch_workflow(workflow_id: str, body: WorkflowCreate, db: Session = Depends(get_db)):
    data = store.update_workflow(db, workflow_id, _body_to_payload(body))
    return _to_out(data)


@router.post("/{workflow_id}/hide", status_code=204)
def hide_workflow(workflow_id: str, db: Session = Depends(get_db)):
    store.hide_workflow(db, workflow_id)


@router.post("/{workflow_id}/export")
def export_workflow(workflow_id: str, db: Session = Depends(get_db)):
    data = store.export_workflow(db, workflow_id)
    return JSONResponse(content=data)


@router.post("/{workflow_id}/validate", response_model=WorkflowValidationOut)
def validate_workflow(workflow_id: str, db: Session = Depends(get_db)):
    return _validation_out(store.validate_workflow_by_id(db, workflow_id))


@router.post("/validate", response_model=WorkflowValidationOut)
def validate_workflow_body(body: WorkflowCreate):
    return _validation_out(store.validate_payload(_body_to_payload(body)))
