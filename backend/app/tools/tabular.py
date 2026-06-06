from __future__ import annotations

import json

from sqlalchemy import select

from app.db.models import TabularCell, TabularReview
from app.tools.context import ToolContext
from app.tools.response import tool_json


def bind_tabular_tools(ctx: ToolContext) -> list:
    tools = []

    def list_tabular_reviews() -> str:
        rows = ctx.db.scalars(
            select(TabularReview).where(TabularReview.workspace_id == ctx.workspace_id)
        ).all()
        data = [{"id": r.id, "title": r.title} for r in rows]
        return tool_json(refused=False, content=json.dumps(data), tier="B")

    list_tabular_reviews.tool_info = {
        "name": "list_tabular_reviews",
        "description": "List tabular reviews in workspace.",
    }
    tools.append(list_tabular_reviews)

    def read_tabular_cells(review_id: str, limit: str = "50") -> str:
        lim = int(limit)
        cells = ctx.db.scalars(
            select(TabularCell).where(TabularCell.review_id == review_id).limit(lim)
        ).all()
        data = [
            {
                "id": c.id,
                "document_id": c.document_id,
                "column_key": c.column_key,
                "summary": c.summary,
                "status": c.status,
            }
            for c in cells
        ]
        return tool_json(refused=False, content=json.dumps(data), tier="B")

    read_tabular_cells.tool_info = {
        "name": "read_tabular_cells",
        "description": "Read tabular cells for a review (Tier B).",
    }
    tools.append(read_tabular_cells)

    return tools
