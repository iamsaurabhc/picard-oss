from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Chunk, Entity, MetadataTag, PageEntity
from app.services.fts_search import _chunk_is_informative


@dataclass
class DocumentContext:
    document_ids: list[str] = field(default_factory=list)
    doc_type: str | None = None
    parties: list[str] = field(default_factory=list)
    governing_law: str | None = None
    entity_samples: dict[str, list[str]] = field(default_factory=dict)
    heading_samples: list[str] = field(default_factory=list)
    page_previews: list[str] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        lines = ["Document context (use vocabulary from these excerpts when choosing FTS terms):"]
        if self.doc_type:
            lines.append(f"- Document type: {self.doc_type}")
        if self.parties:
            lines.append(f"- Parties: {', '.join(self.parties[:8])}")
        if self.governing_law:
            lines.append(f"- Governing law: {self.governing_law}")
        if self.entity_samples:
            for etype, values in sorted(self.entity_samples.items()):
                if values:
                    lines.append(f"- {etype}: {', '.join(values[:6])}")
        if self.heading_samples:
            lines.append(f"- Section headings: {' | '.join(self.heading_samples[:5])}")
        for i, preview in enumerate(self.page_previews[:3], start=1):
            lines.append(f"- Preview {i}: {preview[:400]}")
        if len(lines) == 1:
            lines.append("- (No indexed metadata available — infer terms from the user question.)")
        return "\n".join(lines)


def build_document_context(
    db: Session,
    *,
    workspace_id: str | None,
    document_ids: list[str] | None,
) -> DocumentContext:
    ctx = DocumentContext(document_ids=list(document_ids or []))
    if not document_ids:
        return ctx

    tags = db.scalars(
        select(MetadataTag).where(MetadataTag.document_id.in_(document_ids))
    ).all()
    party_values: list[str] = []
    for tag in tags:
        key = tag.tag_key.casefold()
        if key == "doc_type" and not ctx.doc_type:
            ctx.doc_type = tag.tag_value
        elif key == "governing_law" and not ctx.governing_law:
            ctx.governing_law = tag.tag_value
        elif key.startswith("party_"):
            party_values.append(tag.tag_value)
    if party_values:
        ctx.parties = _dedupe_strs(party_values)

    if workspace_id:
        entity_rows = db.execute(
            select(Entity.entity_type, Entity.display_value, func.sum(PageEntity.mention_count))
            .join(PageEntity, PageEntity.entity_id == Entity.id)
            .where(
                Entity.workspace_id == workspace_id,
                PageEntity.document_id.in_(document_ids),
            )
            .group_by(Entity.entity_type, Entity.display_value)
            .order_by(func.sum(PageEntity.mention_count).desc())
            .limit(40)
        ).all()
        for etype, display, _count in entity_rows:
            ctx.entity_samples.setdefault(etype, [])
            if display and display not in ctx.entity_samples[etype]:
                ctx.entity_samples[etype].append(display)
            if len(ctx.entity_samples[etype]) >= 6:
                continue

    headings = db.scalars(
        select(Chunk.heading_path)
        .where(
            Chunk.document_id.in_(document_ids),
            Chunk.heading_path.isnot(None),
            Chunk.heading_path != "",
        )
        .distinct()
        .limit(8)
    ).all()
    ctx.heading_samples = [h for h in headings if h][:5]

    early = db.scalars(
        select(Chunk)
        .where(Chunk.document_id.in_(document_ids))
        .order_by(Chunk.page_number, Chunk.id)
        .limit(12)
    ).all()
    previews: list[str] = []
    for chunk in early:
        text = (chunk.text_content or "").strip().replace("\n", " ")
        if _chunk_is_informative(text) and text not in previews:
            previews.append(text[:500])
        if len(previews) >= 2:
            break

    if len(previews) < 2:
        substantive = db.scalars(
            select(Chunk)
            .where(Chunk.document_id.in_(document_ids))
            .order_by(Chunk.page_number)
        ).all()
        for chunk in substantive:
            text = (chunk.text_content or "").strip().replace("\n", " ")
            if _chunk_is_informative(text) and text[:500] not in previews:
                previews.append(text[:500])
            if len(previews) >= 3:
                break

    ctx.page_previews = previews
    return ctx


def _dedupe_strs(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        key = v.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out
