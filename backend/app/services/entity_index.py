from __future__ import annotations

import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import utc_now_iso
from app.services.entity_extraction import extract_entities_for_document
from app.services.entity_extraction.recognizers.rules import (
    AMOUNT_PATTERN,
    CONDITION_PATTERN,
    COURT_PATTERN,
    DATE_PATTERN,
    IDENTIFIER_PATTERN,
    LEGAL_ACTOR_PATTERN,
    ORG_PARTY_PATTERN,
    PARTY_PATTERN,
    TITLE_CASE,
    extract_rule_mentions,
    normalize_amount,
    normalize_condition,
    normalize_date,
    normalize_legal_actor,
    normalize_party,
)
from app.services.entity_extraction.types import ExtractedMention

# Back-compat aliases used by constraint_planner and tests
extract_mentions_from_text = extract_rule_mentions


def create_entity_extract_job(db: Session, document_id: str) -> str:
    from app.db.models import Job

    job_id = str(uuid.uuid4())
    now = utc_now_iso()
    db.add(
        Job(
            id=job_id,
            job_type="entity_extract",
            payload_json=json.dumps({"document_id": document_id}),
            status="pending",
            progress=0.0,
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    return job_id


# --- Query-side helpers (CARP) ---


def resolve_party_canonicals(
    db: Session,
    workspace_id: str,
    *,
    canonical: str,
    surfaces: list[str] | None = None,
) -> list[str]:
    """Workspace party entities matching query canonical and surface forms."""
    from app.db.models import Entity

    surfaces = surfaces or []
    tokens = [t for t in canonical.split() if len(t) > 2]
    primary = tokens[0] if tokens else canonical
    matched: set[str] = set()

    rows = db.scalars(
        select(Entity.canonical_value).where(
            Entity.workspace_id == workspace_id,
            Entity.entity_type == "party",
        )
    ).all()

    primary_cf = primary.casefold() if primary else ""
    for cv in rows:
        cv_cf = cv.casefold()
        if cv == canonical:
            matched.add(cv)
            continue
        if any(s.casefold() == cv_cf or s.casefold() in cv_cf or cv_cf in s.casefold() for s in surfaces):
            matched.add(cv)
            continue
        if primary_cf and primary_cf in cv_cf:
            if len(tokens) <= 1 or all(t.casefold() in cv_cf for t in tokens):
                matched.add(cv)
    if canonical and not matched:
        matched.add(canonical)
    return sorted(matched)


def lookup_documents_for_party(
    db: Session,
    workspace_id: str,
    canonical_values: list[str],
    document_ids: list[str] | None = None,
    *,
    limit: int = 12,
) -> list[tuple[str, int]]:
    """Documents mentioning any of the party canonicals, sorted by mention_count desc."""
    from app.db.models import Entity, PageEntity

    if not canonical_values:
        return []

    stmt = (
        select(PageEntity.document_id, func.sum(PageEntity.mention_count).label("cnt"))
        .join(Entity, Entity.id == PageEntity.entity_id)
        .where(
            Entity.workspace_id == workspace_id,
            Entity.entity_type == "party",
            Entity.canonical_value.in_(canonical_values),
        )
        .group_by(PageEntity.document_id)
        .order_by(func.sum(PageEntity.mention_count).desc())
        .limit(limit)
    )
    if document_ids:
        stmt = stmt.where(PageEntity.document_id.in_(document_ids))
    rows = db.execute(stmt).all()
    return [(r[0], int(r[1])) for r in rows]


def lookup_documents_for_party_tokens(
    db: Session,
    workspace_id: str,
    tokens: list[str],
    document_ids: list[str] | None = None,
    *,
    limit: int = 64,
) -> list[tuple[str, int]]:
    """Documents with party entities whose canonical contains any token (substring match)."""
    from app.db.models import Entity, PageEntity

    from sqlalchemy import or_

    cleaned = [t.strip() for t in tokens if t and len(t.strip()) > 2]
    if not cleaned:
        return []

    token_filters = [
        Entity.canonical_value.ilike(f"%{t}%") for t in cleaned[:6]
    ]
    stmt = (
        select(PageEntity.document_id, func.sum(PageEntity.mention_count).label("cnt"))
        .join(Entity, Entity.id == PageEntity.entity_id)
        .where(
            Entity.workspace_id == workspace_id,
            Entity.entity_type == "party",
            or_(*token_filters),
        )
        .group_by(PageEntity.document_id)
        .order_by(func.sum(PageEntity.mention_count).desc())
        .limit(limit)
    )
    if document_ids:
        stmt = stmt.where(PageEntity.document_id.in_(document_ids))
    rows = db.execute(stmt).all()
    return [(r[0], int(r[1])) for r in rows]


def count_documents_for_party(
    db: Session,
    workspace_id: str,
    canonical_values: list[str],
    document_ids: list[str] | None = None,
) -> int:
    """Distinct documents mentioning any party canonical (unlimited for manifest totals)."""
    from app.db.models import Entity, PageEntity

    if not canonical_values:
        return 0

    stmt = select(func.count(func.distinct(PageEntity.document_id))).select_from(PageEntity).join(
        Entity, Entity.id == PageEntity.entity_id
    ).where(
        Entity.workspace_id == workspace_id,
        Entity.entity_type == "party",
        Entity.canonical_value.in_(canonical_values),
    )
    if document_ids:
        stmt = stmt.where(PageEntity.document_id.in_(document_ids))
    return int(db.scalar(stmt) or 0)


def lookup_pages_for_party_in_document(
    db: Session,
    workspace_id: str,
    document_id: str,
    canonical_values: list[str],
) -> set[int]:
    from app.db.models import Entity, PageEntity

    stmt = (
        select(PageEntity.page_number)
        .join(Entity, Entity.id == PageEntity.entity_id)
        .where(
            Entity.workspace_id == workspace_id,
            Entity.entity_type == "party",
            Entity.canonical_value.in_(canonical_values),
            PageEntity.document_id == document_id,
        )
    )
    return {int(r[0]) for r in db.execute(stmt).all()}


def lookup_pages_for_constraint(
    db: Session,
    workspace_id: str,
    entity_type: str,
    canonical_value: str,
    document_ids: list[str] | None = None,
) -> set[tuple[str, int]]:
    from app.db.models import Entity, PageEntity

    stmt = (
        select(PageEntity.document_id, PageEntity.page_number)
        .join(Entity, Entity.id == PageEntity.entity_id)
        .where(
            Entity.workspace_id == workspace_id,
            Entity.entity_type == entity_type,
            Entity.canonical_value == canonical_value,
        )
    )
    if document_ids:
        stmt = stmt.where(PageEntity.document_id.in_(document_ids))
    rows = db.execute(stmt).all()
    return {(r[0], r[1]) for r in rows}


def intersect_page_sets(sets: list[set[tuple[str, int]]]) -> set[tuple[str, int]]:
    if not sets:
        return set()
    ordered = sorted(sets, key=len)
    result = set(ordered[0])
    for s in ordered[1:]:
        result &= s
        if not result:
            break
    return result


def count_pages_for_constraint(
    db: Session,
    workspace_id: str,
    entity_type: str,
    canonical_value: str,
    document_ids: list[str] | None = None,
) -> int:
    return len(lookup_pages_for_constraint(db, workspace_id, entity_type, canonical_value, document_ids))


def partial_overlap_diagnostics(
    db: Session,
    workspace_id: str,
    constraints: list,
    document_ids: list[str] | None = None,
) -> dict:
    page_sets: dict[str, set[tuple[str, int]]] = {}
    for c in constraints:
        key = f"{c.type}_{c.canonical.replace(' ', '_')}"
        page_sets[key] = lookup_pages_for_constraint(
            db, workspace_id, c.type, c.canonical, document_ids
        )
    diagnostics: dict = {}
    for c in constraints:
        key = f"{c.type}_{c.canonical.replace(' ', '_')}"
        diagnostics[f"{c.type}_{c.canonical}_pages"] = len(page_sets.get(key, set()))

    if len(constraints) >= 2:
        for i in range(len(constraints)):
            for j in range(i + 1, len(constraints)):
                ki = f"{constraints[i].type}_{constraints[i].canonical.replace(' ', '_')}"
                kj = f"{constraints[j].type}_{constraints[j].canonical.replace(' ', '_')}"
                overlap = len(page_sets.get(ki, set()) & page_sets.get(kj, set()))
                diagnostics[f"{constraints[i].type}_and_{constraints[j].type}_pages"] = overlap
    return diagnostics


def lookup_section_pages_for_constraint(
    db: Session,
    workspace_id: str,
    entity_type: str,
    canonical_value: str,
    document_ids: list[str] | None = None,
) -> set[tuple[str, int, str | None]]:
    from app.db.models import Chunk, Entity, EntityMention

    entity = db.scalar(
        select(Entity).where(
            Entity.workspace_id == workspace_id,
            Entity.entity_type == entity_type,
            Entity.canonical_value == canonical_value,
        )
    )
    if not entity:
        return set()
    stmt = (
        select(EntityMention.document_id, EntityMention.page_number, Chunk.section_key)
        .join(Chunk, Chunk.id == EntityMention.chunk_id)
        .where(EntityMention.entity_id == entity.id)
    )
    if document_ids:
        stmt = stmt.where(EntityMention.document_id.in_(document_ids))
    rows = db.execute(stmt).all()
    return {(r[0], r[1], r[2]) for r in rows}


__all__ = [
    "AMOUNT_PATTERN",
    "CONDITION_PATTERN",
    "COURT_PATTERN",
    "DATE_PATTERN",
    "IDENTIFIER_PATTERN",
    "LEGAL_ACTOR_PATTERN",
    "ORG_PARTY_PATTERN",
    "PARTY_PATTERN",
    "TITLE_CASE",
    "ExtractedMention",
    "create_entity_extract_job",
    "extract_entities_for_document",
    "extract_mentions_from_text",
    "intersect_page_sets",
    "lookup_documents_for_party",
    "lookup_pages_for_constraint",
    "lookup_pages_for_party_in_document",
    "resolve_party_canonicals",
    "lookup_section_pages_for_constraint",
    "normalize_amount",
    "normalize_condition",
    "normalize_date",
    "normalize_legal_actor",
    "normalize_party",
    "partial_overlap_diagnostics",
    "count_pages_for_constraint",
]
