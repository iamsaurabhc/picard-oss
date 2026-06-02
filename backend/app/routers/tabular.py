from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.db.session import get_db
from app.schemas import (
    GenerateColumnPromptRequest,
    GenerateColumnPromptResponse,
    TabularBatchGenerateRequest,
    TabularCellOut,
    TabularReviewCreate,
    TabularReviewOut,
    TabularReviewSummary,
    TabularReviewUpdate,
)
from app.services import tabular as tabular_svc
from app.services.tabular_export import build_review_xlsx
from app.services.tabular_extractor import regenerate_cell, stream_batch_generation

router = APIRouter(tags=["tabular"])


@router.get("/workspaces/{workspace_id}/tabular/reviews", response_model=list[TabularReviewSummary])
def list_workspace_reviews(workspace_id: str, db: Session = Depends(get_db)):
    return tabular_svc.list_reviews(db, workspace_id)


@router.post("/tabular/reviews", response_model=TabularReviewOut, status_code=201)
def create_review(body: TabularReviewCreate, db: Session = Depends(get_db)):
    review = tabular_svc.create_review(db, body)
    return tabular_svc.get_review(db, review.id)


@router.get("/tabular/reviews/{review_id}", response_model=TabularReviewOut)
def get_review(review_id: str, db: Session = Depends(get_db)):
    return tabular_svc.get_review(db, review_id)


@router.patch("/tabular/reviews/{review_id}", response_model=TabularReviewOut)
def update_review(review_id: str, body: TabularReviewUpdate, db: Session = Depends(get_db)):
    return tabular_svc.update_review(db, review_id, body)


@router.delete("/tabular/reviews/{review_id}", status_code=204)
def delete_review(review_id: str, db: Session = Depends(get_db)):
    tabular_svc.delete_review(db, review_id)


@router.post("/tabular/generate-column-prompt", response_model=GenerateColumnPromptResponse)
def generate_column_prompt(body: GenerateColumnPromptRequest):
    prompt, from_preset, suggested_format = tabular_svc.generate_column_prompt(
        body.label,
        body.format,
        idea=body.idea,
    )
    return GenerateColumnPromptResponse(
        prompt=prompt,
        from_preset=from_preset,
        suggested_format=suggested_format,  # type: ignore[arg-type]
    )


@router.post("/tabular/reviews/{review_id}/generate/stream")
async def batch_generate_stream(
    review_id: str,
    body: TabularBatchGenerateRequest | None = None,
):
    req = body or TabularBatchGenerateRequest()

    async def event_generator():
        async for payload in stream_batch_generation(review_id, req):
            event = payload.pop("event")
            yield {"event": event, "data": json.dumps(payload)}

    return EventSourceResponse(event_generator())


@router.post("/tabular/cells/{cell_id}/regenerate", response_model=TabularCellOut)
def regenerate_cell_endpoint(cell_id: str, db: Session = Depends(get_db)):
    return regenerate_cell(db, cell_id)


@router.get("/tabular/reviews/{review_id}/export.xlsx")
def export_review_xlsx(review_id: str, db: Session = Depends(get_db)):
    review = tabular_svc.get_review(db, review_id)
    data = build_review_xlsx(db, review_id)
    safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in review.title)[:80] or "review"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.xlsx"'},
    )
