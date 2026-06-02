import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Workspace
from app.db.session import get_db, utc_now_iso
from app.schemas import WorkspaceCreate, WorkspaceOut, WorkspaceOverviewOut, WorkspaceUpdate
from app.services.workspace_overview import get_workspace_overview

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(db: Session = Depends(get_db)):
    return db.scalars(select(Workspace).order_by(Workspace.updated_at.desc())).all()


@router.post("", response_model=WorkspaceOut, status_code=201)
def create_workspace(body: WorkspaceCreate, db: Session = Depends(get_db)):
    now = utc_now_iso()
    ws = Workspace(
        id=str(uuid.uuid4()),
        name=body.name,
        matter_ref=body.matter_ref,
        created_at=now,
        updated_at=now,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


@router.get("/{workspace_id}", response_model=WorkspaceOut)
def get_workspace(workspace_id: str, db: Session = Depends(get_db)):
    ws = db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@router.get("/{workspace_id}/overview", response_model=WorkspaceOverviewOut)
def workspace_overview(workspace_id: str, db: Session = Depends(get_db)):
    return get_workspace_overview(db, workspace_id)


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
def update_workspace(workspace_id: str, body: WorkspaceUpdate, db: Session = Depends(get_db)):
    ws = db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if body.name is not None:
        ws.name = body.name
    if body.matter_ref is not None:
        ws.matter_ref = body.matter_ref
    ws.updated_at = utc_now_iso()
    db.commit()
    db.refresh(ws)
    return ws


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace(workspace_id: str, db: Session = Depends(get_db)):
    ws = db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    db.delete(ws)
    db.commit()
