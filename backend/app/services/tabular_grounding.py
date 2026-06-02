from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Entity, EntityMention, MetadataTag
from app.services.document_context import build_document_context
from app.services.metadata_extractor import _doc_type_from_filename


def _tag_value(db: Session, document_id: str, tag_key: str) -> str | None:
    tag = db.scalar(
        select(MetadataTag).where(
            MetadataTag.document_id == document_id,
            MetadataTag.tag_key == tag_key,
        )
    )
    return tag.tag_value if tag and tag.tag_value else None


def document_doc_type(db: Session, document_id: str, file_name: str | None = None) -> str | None:
    dt = _tag_value(db, document_id, "doc_type")
    if dt:
        return dt
    if file_name:
        return _doc_type_from_filename(file_name)
    return None


def indexed_parties_for_document(db: Session, document_id: str, workspace_id: str) -> list[str]:
    parties: list[str] = []
    tags = db.scalars(
        select(MetadataTag).where(
            MetadataTag.document_id == document_id,
            MetadataTag.tag_key.like("party_%"),
        )
    ).all()
    for tag in tags:
        if tag.tag_value and tag.tag_value not in parties:
            parties.append(tag.tag_value)

    rows = db.execute(
        select(Entity.display_value)
        .join(EntityMention, EntityMention.entity_id == Entity.id)
        .where(
            Entity.workspace_id == workspace_id,
            Entity.entity_type == "party",
            EntityMention.document_id == document_id,
        )
        .distinct()
        .limit(12)
    ).all()
    for (display,) in rows:
        if display and display not in parties:
            parties.append(display)
    return parties


def indexed_dates_for_document(
    db: Session, document_id: str, workspace_id: str, *, max_page: int = 5
) -> list[str]:
    rows = db.execute(
        select(Entity.display_value, EntityMention.page_number)
        .join(EntityMention, EntityMention.entity_id == Entity.id)
        .where(
            Entity.workspace_id == workspace_id,
            Entity.entity_type == "date",
            EntityMention.document_id == document_id,
            EntityMention.page_number <= max_page,
        )
        .order_by(EntityMention.page_number)
        .limit(8)
    ).all()
    seen: set[str] = set()
    out: list[str] = []
    for display, _page in rows:
        if display and display not in seen:
            seen.add(display)
            out.append(display)
    return out


def metadata_for_column(db: Session, document_id: str, column_key: str) -> dict[str, str]:
    """Return ingest tags relevant to validation retries."""
    out: dict[str, str] = {}
    if column_key == "governing_law":
        val = _tag_value(db, document_id, "governing_law")
        if val:
            out["governing_law"] = val
    if column_key == "effective_date":
        val = _tag_value(db, document_id, "effective_date")
        if val:
            out["effective_date"] = val
    return out


def build_tabular_grounding(
    db: Session,
    *,
    document_id: str,
    workspace_id: str,
    column_key: str,
    file_name: str | None = None,
) -> str:
    lines: list[str] = []

    doc_type = document_doc_type(db, document_id, file_name)
    if doc_type:
        lines.append(f"- Document type: {doc_type}")

    if column_key == "parties":
        parties = indexed_parties_for_document(db, document_id, workspace_id)
        if parties:
            lines.append(f"- Parties from index: {', '.join(parties[:12])}")

    if column_key == "governing_law":
        gov = _tag_value(db, document_id, "governing_law")
        if gov:
            lines.append(f"- Governing law / jurisdiction from index: {gov}")

    if column_key == "effective_date":
        eff = _tag_value(db, document_id, "effective_date")
        if eff:
            lines.append(f"- Effective / order date from index: {eff}")
        dates = indexed_dates_for_document(db, document_id, workspace_id)
        if dates:
            lines.append(f"- Date entities (early pages): {', '.join(dates[:6])}")

    ctx = build_document_context(db, workspace_id=workspace_id, document_ids=[document_id])
    if ctx.parties and column_key == "parties":
        extra = [p for p in ctx.parties if not any(p in ln for ln in lines)]
        if extra:
            lines.append(f"- Document context parties: {', '.join(extra[:8])}")
    if ctx.governing_law and column_key == "governing_law" and not any("Governing law" in ln for ln in lines):
        lines.append(f"- Document context governing law: {ctx.governing_law}")
    if ctx.page_previews and column_key in ("parties", "governing_law", "effective_date"):
        for i, preview in enumerate(ctx.page_previews[:2], start=1):
            lines.append(f"- Early page preview {i}: {preview[:400]}")

    if not lines:
        return ""
    return (
        "Indexed evidence (cross-check against Source chunks; cite chunk_ids from Source chunks only):\n"
        + "\n".join(lines)
    )


def parties_summary_misses_index(summary: str, indexed_parties: list[str]) -> bool:
    if not indexed_parties:
        return False
    lower = (summary or "").casefold()
    if "not specified" in lower or "not addressed" in lower:
        return True
    matched = 0
    for party in indexed_parties:
        tokens = [t for t in party.casefold().split() if len(t) > 2]
        if not tokens:
            continue
        if any(t in lower for t in tokens[:3]):
            matched += 1
    return matched < max(1, len(indexed_parties) // 2)


def metadata_summary_misses(summary: str, metadata: dict[str, str]) -> bool:
    if not metadata:
        return False
    lower = (summary or "").casefold()
    if "not specified" in lower or "not addressed" in lower or "n/a" in lower:
        return True
    for _key, value in metadata.items():
        tokens = [t for t in value.casefold().split() if len(t) > 2]
        if tokens and not any(t in lower for t in tokens[:2]):
            return True
    return False
