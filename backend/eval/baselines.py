from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.fts_search import fts_search


def or_bm25_search(
    db: Session,
    *,
    terms: list[str],
    workspace_id: str,
    document_ids: list[str] | None,
    top_k: int = 8,
) -> list[str]:
    query = " OR ".join(f'"{t}"' if " " in t else t for t in terms)
    hits = fts_search(db, query=query, workspace_id=workspace_id, document_ids=document_ids, top_k=top_k)
    return [h.chunk_id for h in hits]


def strict_and_search(
    db: Session,
    *,
    terms: list[str],
    workspace_id: str,
    document_ids: list[str] | None,
    top_k: int = 8,
) -> list[str]:
    query = " AND ".join(f'"{t}"' if " " in t else t for t in terms)
    try:
        hits = fts_search(db, query=query, workspace_id=workspace_id, document_ids=document_ids, top_k=top_k)
        return [h.chunk_id for h in hits]
    except Exception:
        return []
