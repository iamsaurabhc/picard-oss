from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Document, Entity, EntityMention, MetadataTag, TabularReview, Workspace
from app.schemas import (
    DocumentOut,
    DocTypeCountOut,
    PartyHighlightOut,
    WorkspaceDocumentCountsOut,
    WorkspaceOut,
    WorkspaceOverviewOut,
)


def get_workspace_overview(db: Session, workspace_id: str) -> WorkspaceOverviewOut:
    ws = db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    status_rows = db.execute(
        select(Document.parse_status, func.count())
        .where(Document.workspace_id == workspace_id)
        .group_by(Document.parse_status)
    ).all()
    counts = {status: cnt for status, cnt in status_rows}
    doc_counts = WorkspaceDocumentCountsOut(
        total=sum(counts.values()),
        done=counts.get("done", 0),
        pending=counts.get("pending", 0),
        parsing=counts.get("parsing", 0),
        error=counts.get("error", 0),
    )

    tabular_reviews = db.scalar(
        select(func.count()).select_from(TabularReview).where(TabularReview.workspace_id == workspace_id)
    ) or 0

    party_rows = db.execute(
        select(Entity.display_value, func.count(func.distinct(EntityMention.document_id)))
        .join(EntityMention, EntityMention.entity_id == Entity.id)
        .where(
            Entity.workspace_id == workspace_id,
            Entity.entity_type == "party",
        )
        .group_by(Entity.id, Entity.display_value)
        .order_by(func.count(func.distinct(EntityMention.document_id)).desc())
        .limit(12)
    ).all()
    parties = [
        PartyHighlightOut(display_value=display, document_count=doc_count)
        for display, doc_count in party_rows
        if display
    ]

    dtype_rows = db.execute(
        select(MetadataTag.tag_value, func.count(func.distinct(MetadataTag.document_id)))
        .join(Document, Document.id == MetadataTag.document_id)
        .where(
            Document.workspace_id == workspace_id,
            MetadataTag.tag_key == "doc_type",
            MetadataTag.tag_value.isnot(None),
        )
        .group_by(MetadataTag.tag_value)
        .order_by(func.count(func.distinct(MetadataTag.document_id)).desc())
    ).all()
    doc_types = [
        DocTypeCountOut(doc_type=dt, count=cnt) for dt, cnt in dtype_rows if dt
    ]

    recent = db.scalars(
        select(Document)
        .where(Document.workspace_id == workspace_id)
        .order_by(Document.created_at.desc())
        .limit(5)
    ).all()

    return WorkspaceOverviewOut(
        workspace=WorkspaceOut.model_validate(ws),
        documents=doc_counts,
        tabular_reviews=tabular_reviews,
        parties=parties,
        doc_types=doc_types,
        recent_documents=[DocumentOut.model_validate(d) for d in recent],
    )
