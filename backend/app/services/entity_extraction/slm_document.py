from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Chunk, Document, Entity, EntityMention, MetadataTag, PageEntity
from app.services.entity_extraction.recognizers.rules import normalize_amount, normalize_date, normalize_party
from app.services.entity_extraction.types import ExtractedMention
from app.services.model_router import ModelRole, completion, llm_available

logger = logging.getLogger(__name__)


def _upsert_entity(db: Session, workspace_id: str, entity_type: str, canonical: str, display: str) -> Entity:
    existing = db.scalar(
        select(Entity).where(
            Entity.workspace_id == workspace_id,
            Entity.entity_type == entity_type,
            Entity.canonical_value == canonical,
        )
    )
    if existing:
        return existing
    entity = Entity(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        entity_type=entity_type,
        canonical_value=canonical,
        display_value=display,
    )
    db.add(entity)
    db.flush()
    return entity


def _record_mention(
    db: Session,
    *,
    entity: Entity,
    document_id: str,
    chunk: Chunk,
    mention: ExtractedMention,
) -> None:
    db.add(
        EntityMention(
            id=str(uuid.uuid4()),
            entity_id=entity.id,
            document_id=document_id,
            chunk_id=chunk.id,
            page_number=chunk.page_number,
            char_start=mention.char_start,
            char_end=mention.char_end,
            surface_text=mention.surface_text,
            confidence=mention.confidence,
            source=mention.source,
        )
    )
    pe = db.get(PageEntity, (document_id, chunk.page_number, entity.id))
    if pe:
        pe.mention_count += 1
    else:
        db.add(
            PageEntity(
                document_id=document_id,
                page_number=chunk.page_number,
                entity_id=entity.id,
                mention_count=1,
            )
        )
    db.flush()


DOCUMENT_SEMANTICS_PROMPT = """Extract legal document semantics from the preview below.
Return JSON only:
{{
  "doc_type": "contract|nda|msa|lease|litigation|regulatory|other",
  "parties": [
    {{"display": "Google LLC", "role": "defendant", "pages": [1, 2]}}
  ],
  "dates": [{{"surface": "03.12.2013", "iso": "2013-12-03", "pages": [2]}}],
  "identifiers": [{{"surface": "Case No. 39/2018", "pages": [1]}}],
  "amounts": [{{"surface": "£1,000", "canonical": "1000_gbp", "pages": [3]}}],
  "governing_law": "India" or null,
  "effective_date": "YYYY-MM-DD" or null
}}

Rules:
- List only parties, dates, identifiers, and amounts that appear in the preview text.
- pages must be page numbers present in the preview (integers).
- For parties use exact surface spelling from the document.
- doc_type: regulatory for competition commission / CCI orders; litigation for court judgments.

File name: {file_name}

Document preview (by page):
{preview}
"""


def _upsert_tag(db: Session, document_id: str, key: str, value: str) -> None:
    existing = db.scalar(
        select(MetadataTag).where(
            MetadataTag.document_id == document_id,
            MetadataTag.tag_key == key,
        )
    )
    if existing:
        existing.tag_value = value
    else:
        db.add(
            MetadataTag(
                id=str(uuid.uuid4()),
                document_id=document_id,
                tag_key=key,
                tag_value=value,
                source_chunk_id=None,
            )
        )


def _chunks_by_page(db: Session, document_id: str, max_pages: int = 5) -> dict[int, list[Chunk]]:
    chunks = db.scalars(
        select(Chunk)
        .where(Chunk.document_id == document_id, Chunk.page_number <= max_pages)
        .order_by(Chunk.page_number)
    ).all()
    by_page: dict[int, list[Chunk]] = {}
    for c in chunks:
        by_page.setdefault(c.page_number, []).append(c)
    return by_page


def _build_preview(by_page: dict[int, list[Chunk]], *, chars_per_page: int = 500) -> str:
    lines: list[str] = []
    for page in sorted(by_page):
        text = " ".join((c.text_content or "").strip() for c in by_page[page])
        lines.append(f"Page {page}: {text[:chars_per_page]}")
    return "\n".join(lines)


def _find_chunk_for_surface(
    by_page: dict[int, list[Chunk]],
    page: int,
    surface: str,
) -> Chunk | None:
    surface_cf = surface.casefold()
    for chunk in by_page.get(page, []):
        if surface_cf in (chunk.text_content or "").casefold():
            return chunk
    for chunk in by_page.get(page, []):
        if chunk.text_content:
            return chunk
    return None


def _clear_document_entities(db: Session, document_id: str) -> None:
    """Clear entity mentions for this document before SLM re-index."""
    db.execute(delete(EntityMention).where(EntityMention.document_id == document_id))
    db.execute(delete(PageEntity).where(PageEntity.document_id == document_id))
    db.flush()


def extract_document_semantics(db: Session, document_id: str) -> int:
    """One SLM call per document: metadata tags + entity index (parties, dates, etc.)."""
    if not settings.enable_slm_entity_extract or not llm_available():
        return 0

    doc = db.get(Document, document_id)
    if not doc:
        return 0

    by_page = _chunks_by_page(db, document_id, max_pages=settings.slm_entity_max_pages)
    if not by_page:
        return 0

    preview = _build_preview(by_page)
    raw = completion(
        messages=[{
            "role": "user",
            "content": DOCUMENT_SEMANTICS_PROMPT.format(
                file_name=doc.file_name,
                preview=preview,
            ),
        }],
        role=ModelRole.SLM,
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    if not raw:
        return 0

    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end])
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("document semantics parse failed: %s", exc)
        return 0

    _clear_document_entities(db, document_id)

    if data.get("doc_type"):
        _upsert_tag(db, document_id, "doc_type", str(data["doc_type"]))
    if data.get("governing_law"):
        _upsert_tag(db, document_id, "governing_law", str(data["governing_law"]))
    if data.get("effective_date"):
        _upsert_tag(db, document_id, "effective_date", str(data["effective_date"]))

    for i, party in enumerate(data.get("parties") or []):
        if isinstance(party, str):
            display = party
            pages: list[int] = []
        else:
            display = str(party.get("display") or "")
            pages = [int(p) for p in (party.get("pages") or []) if isinstance(p, (int, float))]
        if display:
            _upsert_tag(db, document_id, f"party_{i + 1}", display)

    count = 0
    for party in data.get("parties") or []:
        if isinstance(party, str):
            display = party
            pages = list(by_page.keys())[:1]
        else:
            display = str(party.get("display") or "").strip()
            pages = [int(p) for p in (party.get("pages") or []) if isinstance(p, (int, float))]
        if not display or not pages:
            continue
        canonical = normalize_party(display)
        entity = _upsert_entity(db, doc.workspace_id, "party", canonical, display)
        for page in pages:
            chunk = _find_chunk_for_surface(by_page, page, display)
            if not chunk:
                continue
            mention = ExtractedMention(
                "party", canonical, display, display, None, None,
                confidence=0.9, source="slm",
            )
            _record_mention(db, entity=entity, document_id=document_id, chunk=chunk, mention=mention)
            count += 1

    for item in data.get("dates") or []:
        if not isinstance(item, dict):
            continue
        surface = str(item.get("surface") or "")
        iso = item.get("iso") or normalize_date(surface)
        pages = [int(p) for p in (item.get("pages") or []) if isinstance(p, (int, float))]
        if not iso or not pages:
            continue
        entity = _upsert_entity(db, doc.workspace_id, "date", iso, surface or iso)
        for page in pages:
            chunk = _find_chunk_for_surface(by_page, page, surface) if surface else None
            if not chunk and page in by_page:
                chunk = by_page[page][0]
            if chunk:
                _record_mention(
                    db, entity=entity, document_id=document_id, chunk=chunk,
                    mention=ExtractedMention("date", iso, surface or iso, surface or iso, None, None, source="slm"),
                )
                count += 1

    for item in data.get("identifiers") or []:
        if not isinstance(item, dict):
            continue
        surface = str(item.get("surface") or "").strip()
        pages = [int(p) for p in (item.get("pages") or []) if isinstance(p, (int, float))]
        if not surface or not pages:
            continue
        canonical = surface.casefold()
        entity = _upsert_entity(db, doc.workspace_id, "identifier", canonical, surface)
        for page in pages:
            chunk = _find_chunk_for_surface(by_page, page, surface)
            if chunk:
                _record_mention(
                    db, entity=entity, document_id=document_id, chunk=chunk,
                    mention=ExtractedMention("identifier", canonical, surface, surface, None, None, source="slm"),
                )
                count += 1

    for item in data.get("amounts") or []:
        if not isinstance(item, dict):
            continue
        surface = str(item.get("surface") or "")
        canonical = item.get("canonical") or normalize_amount(surface)
        pages = [int(p) for p in (item.get("pages") or []) if isinstance(p, (int, float))]
        if not canonical or not pages:
            continue
        entity = _upsert_entity(db, doc.workspace_id, "amount", str(canonical), surface or str(canonical))
        for page in pages:
            chunk = _find_chunk_for_surface(by_page, page, surface) if surface else None
            if not chunk and page in by_page:
                chunk = by_page[page][0]
            if chunk:
                _record_mention(
                    db, entity=entity, document_id=document_id, chunk=chunk,
                    mention=ExtractedMention("amount", str(canonical), surface or str(canonical), surface or str(canonical), None, None, source="slm"),
                )
                count += 1

    db.commit()
    return count
