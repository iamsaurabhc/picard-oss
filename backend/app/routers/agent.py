from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas import AgentRunOut
from app.services.agent_runs_store import agent_run_to_dict, get_agent_run

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/runs/{run_id}", response_model=AgentRunOut)
def get_agent_run_route(run_id: str, db: Session = Depends(get_db)):
    try:
        data = agent_run_to_dict(get_agent_run(db, run_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AgentRunOut(**data)
