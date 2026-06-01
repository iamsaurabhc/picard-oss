from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Document, Entity, MetadataTag
from app.db.models import PageEntity
from app.services.model_router import llm_available


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


def _rule_extract_from_index(db: Session, doc: Document) -> None:
    """Derive party tags from entity index when SLM is unavailable."""
    parties = db.scalars(
        select(Entity.display_value)
        .join(PageEntity, PageEntity.entity_id == Entity.id)
        .where(
            PageEntity.document_id == doc.id,
            Entity.entity_type == "party",
        )
        .distinct()
        .limit(5)
    ).all()
    for i, party in enumerate(parties):
        _upsert_tag(db, doc.id, f"party_{i + 1}", party)


def extract_metadata_for_document(db: Session, document_id: str) -> None:
    """Metadata is written by extract_document_semantics when SLM entity extract is enabled."""
    doc = db.get(Document, document_id)
    if not doc:
        return

    has_doc_type = db.scalar(
        select(MetadataTag.id).where(
            MetadataTag.document_id == document_id,
            MetadataTag.tag_key == "doc_type",
        )
    )

    if settings.enable_slm_entity_extract and llm_available():
        if not has_doc_type:
            from app.services.entity_extraction.slm_document import extract_document_semantics

            extract_document_semantics(db, document_id)
            return

    if settings.enable_metadata_llm and llm_available():
        from app.services.entity_extraction.slm_document import extract_document_semantics

        extract_document_semantics(db, document_id)
        db.commit()
        return

    _rule_extract_from_index(db, doc)
    db.commit()
