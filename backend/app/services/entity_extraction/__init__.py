from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Chunk, Document, Entity, EntityMention, MetadataTag, PageEntity
from app.services.entity_extraction.merge import merge_mentions
from app.services.entity_extraction.ner.gliner_engine import extract_ner_mentions, ner_available
from app.services.entity_extraction.profiles import profile_for_doc_type
from app.services.entity_extraction.recognizers.rules import (
    CONDITION_PATTERN,
    extract_rule_mentions,
    normalize_condition,
)
from app.services.entity_extraction.types import ExtractedMention
from app.services.model_router import llm_available


def _doc_type(db: Session, document_id: str) -> str | None:
    tag = db.scalar(
        select(MetadataTag.tag_value).where(
            MetadataTag.document_id == document_id,
            MetadataTag.tag_key == "doc_type",
        )
    )
    return tag


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


def _extract_entities_rule_based(db: Session, document_id: str) -> int:
    doc = db.get(Document, document_id)
    if not doc:
        return 0

    profile = profile_for_doc_type(_doc_type(db, document_id))
    use_ner = settings.enable_ner_entity_extract and ner_available()

    chunks = db.scalars(
        select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.page_number)
    ).all()
    count = 0
    section_condition_entities: dict[str, Entity] = {}

    for chunk in chunks:
        early_doc = chunk.page_number <= 3
        rule_mentions = extract_rule_mentions(chunk.text_content, early_doc=early_doc)
        ner_mentions: list[ExtractedMention] = []
        if use_ner:
            ner_mentions = extract_ner_mentions(chunk.text_content, profile.ner_labels)
        mentions = merge_mentions(rule_mentions, ner_mentions)

        if chunk.chunk_type == "heading":
            for m in CONDITION_PATTERN.finditer(chunk.text_content):
                entity = _upsert_entity(
                    db,
                    doc.workspace_id,
                    "condition",
                    normalize_condition(m.group(0)),
                    m.group(0),
                )
                if chunk.section_key:
                    section_condition_entities[chunk.section_key] = entity

        for mention in mentions:
            entity = _upsert_entity(
                db,
                doc.workspace_id,
                mention.entity_type,
                mention.canonical_value,
                mention.display_value,
            )
            _record_mention(db, entity=entity, document_id=document_id, chunk=chunk, mention=mention)
            count += 1

        if chunk.section_key and chunk.section_key in section_condition_entities:
            entity = section_condition_entities[chunk.section_key]
            _record_mention(
                db,
                entity=entity,
                document_id=document_id,
                chunk=chunk,
                mention=ExtractedMention(
                    entity.entity_type,
                    entity.canonical_value,
                    entity.display_value,
                    chunk.text_content[:80],
                    None,
                    None,
                ),
            )

    db.commit()
    return count


def extract_entities_for_document(db: Session, document_id: str) -> int:
    """SLM document semantics first; optional rule/NER fallback."""
    if settings.enable_slm_entity_extract and llm_available():
        from app.services.entity_extraction.slm_document import extract_document_semantics

        count = extract_document_semantics(db, document_id)
        if count > 0:
            return count

    if settings.enable_rule_entity_extract or settings.enable_regex_nlp:
        return _extract_entities_rule_based(db, document_id)

    return 0
