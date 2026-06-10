"""Dynamic Document Profile — SLM-driven, versioned, cached."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Chunk, Document, MetadataTag
from app.db.session import utc_now_iso
from app.services.model_router import ModelRole, completion, llm_available

logger = logging.getLogger(__name__)

PROFILE_TAG_KEY = "document_profile"
PROFILE_CACHE_TTL_SEC = 300

_profile_cache: dict[str, tuple[float, dict]] = {}


@dataclass
class DocumentProfile:
    profile_version: int = 0
    canonical_kind: str = ""
    kind_labels: list[str] = field(default_factory=list)
    structure: dict[str, Any] = field(default_factory=dict)
    synthesis_outline: list[str] = field(default_factory=list)
    anti_patterns: list[str] = field(default_factory=list)
    confidence: float = 0.0
    source: str = "v0_structure"
    updated_at: str = ""
    amplification_events: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "profile_version": self.profile_version,
            "canonical_kind": self.canonical_kind,
            "kind_labels": self.kind_labels,
            "structure": self.structure,
            "synthesis_outline": self.synthesis_outline,
            "anti_patterns": self.anti_patterns,
            "confidence": self.confidence,
            "source": self.source,
            "updated_at": self.updated_at,
            "amplification_events": self.amplification_events[-3:],
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> DocumentProfile:
        if not data:
            return cls()
        return cls(
            profile_version=int(data.get("profile_version") or 0),
            canonical_kind=str(data.get("canonical_kind") or ""),
            kind_labels=list(data.get("kind_labels") or []),
            structure=dict(data.get("structure") or {}),
            synthesis_outline=list(data.get("synthesis_outline") or []),
            anti_patterns=list(data.get("anti_patterns") or []),
            confidence=float(data.get("confidence") or 0.0),
            source=str(data.get("source") or ""),
            updated_at=str(data.get("updated_at") or ""),
            amplification_events=list(data.get("amplification_events") or []),
        )


def _upsert_profile_tag(db: Session, document_id: str, profile: DocumentProfile) -> None:
    payload = json.dumps(profile.to_dict())
    existing = db.scalar(
        select(MetadataTag).where(
            MetadataTag.document_id == document_id,
            MetadataTag.tag_key == PROFILE_TAG_KEY,
        )
    )
    if existing:
        existing.tag_value = payload
    else:
        db.add(
            MetadataTag(
                id=str(uuid.uuid4()),
                document_id=document_id,
                tag_key=PROFILE_TAG_KEY,
                tag_value=payload,
                source_chunk_id=None,
            )
        )


def invalidate_profile_cache(document_id: str) -> None:
    _profile_cache.pop(document_id, None)


def load_profile(db: Session, document_id: str, *, use_cache: bool = True) -> DocumentProfile:
    if use_cache and document_id in _profile_cache:
        ts, data = _profile_cache[document_id]
        if time.monotonic() - ts < PROFILE_CACHE_TTL_SEC:
            return DocumentProfile.from_dict(data)

    tag = db.scalar(
        select(MetadataTag).where(
            MetadataTag.document_id == document_id,
            MetadataTag.tag_key == PROFILE_TAG_KEY,
        )
    )
    if not tag or not tag.tag_value:
        return DocumentProfile()
    try:
        data = json.loads(tag.tag_value)
    except json.JSONDecodeError:
        return DocumentProfile()
    _profile_cache[document_id] = (time.monotonic(), data)
    return DocumentProfile.from_dict(data)


def load_profiles_for_documents(db: Session, document_ids: list[str]) -> dict[str, DocumentProfile]:
    if not document_ids:
        return {}
    tags = db.scalars(
        select(MetadataTag).where(
            MetadataTag.document_id.in_(document_ids),
            MetadataTag.tag_key == PROFILE_TAG_KEY,
        )
    ).all()
    out: dict[str, DocumentProfile] = {}
    for tag in tags:
        try:
            data = json.loads(tag.tag_value)
            out[tag.document_id] = DocumentProfile.from_dict(data)
            _profile_cache[tag.document_id] = (time.monotonic(), data)
        except json.JSONDecodeError:
            continue
    return out


def build_profile_v0_from_chunks(chunks: list[Chunk]) -> DocumentProfile:
    """Structural profile only — no LLM."""
    table_headers: list[str] = []
    table_row_count = 0
    columns: list[str] = []
    heading_paths: list[str] = []
    sample_rows: list[str] = []

    for chunk in chunks:
        ct = chunk.chunk_type or ""
        if chunk.heading_path and chunk.heading_path not in heading_paths:
            heading_paths.append(chunk.heading_path)
        if ct == "table_header":
            table_headers.append((chunk.text_content or "")[:500])
            if chunk.anchor_json:
                try:
                    anchor = json.loads(chunk.anchor_json)
                    cols = anchor.get("columns")
                    if cols:
                        columns = list(cols)
                except json.JSONDecodeError:
                    pass
        elif ct == "table_row":
            table_row_count += 1
            if len(sample_rows) < 5:
                sample_rows.append((chunk.text_content or "")[:400])
        elif ct == "table":
            table_headers.append((chunk.text_content or "")[:300])

    primary_unit = "table_row" if table_row_count > 0 else ("table" if table_headers else "paragraph")
    structure: dict[str, Any] = {
        "primary_unit": primary_unit,
        "table_count": len(table_headers),
        "table_row_count": table_row_count,
        "columns": columns,
        "heading_paths": heading_paths[:5],
        "sample_row_previews": sample_rows,
    }
    if primary_unit == "table_row" and columns:
        structure["fragmented_tables"] = False

    return DocumentProfile(
        profile_version=0,
        canonical_kind="",
        kind_labels=[],
        structure=structure,
        synthesis_outline=[],
        anti_patterns=["Do not use litigation case skeleton sections unless kind_labels include litigation"],
        confidence=0.4 if table_row_count else 0.2,
        source="v0_structure",
        updated_at=utc_now_iso(),
    )


def save_profile_v0(db: Session, document_id: str, chunks: list[Chunk]) -> DocumentProfile:
    profile = build_profile_v0_from_chunks(chunks)
    _upsert_profile_tag(db, document_id, profile)
    invalidate_profile_cache(document_id)
    return profile


PROFILE_ENRICH_PROMPT = """Analyze this document and produce a dynamic profile for retrieval and answer synthesis.
Return JSON only:
{{
  "canonical_kind": "free-text description of what this document is",
  "kind_labels": ["tag1", "tag2"],
  "column_roles": {{"<exact column header>": "role_label"}},
  "overview_facets": [
    {{"label": "short_label", "question": "question to answer", "fts_terms": ["term1", "term2"]}}
  ],
  "synthesis_outline": ["Section heading 1", "Section heading 2"],
  "anti_patterns": ["things the answer writer should avoid"],
  "confidence": 0.0-1.0
}}

Use ONLY vocabulary from the previews below. Do not invent document kinds not supported by content.

File name: {file_name}

{context_block}
"""


def _profile_context_block(chunks: list[Chunk], doc: Document) -> str:
    paths = list(dict.fromkeys(c.heading_path for c in chunks if c.heading_path))[:8]
    lines = [f"Heading paths: {', '.join(paths)}"]
    for chunk in chunks:
        if chunk.chunk_type in {"table_header", "table_row", "heading", "table"}:
            preview = (chunk.text_content or "").replace("\n", " ")[:450]
            lines.append(f"- [{chunk.chunk_type}] {preview}")
        if len(lines) >= 12:
            break
    return "\n".join(lines)


def enrich_profile_with_slm(db: Session, document_id: str) -> DocumentProfile | None:
    if not llm_available():
        return None
    doc = db.get(Document, document_id)
    if not doc:
        return None
    chunks = list(
        db.scalars(
            select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.page_number, Chunk.id)
        ).all()
    )
    if not chunks:
        return None

    prior = load_profile(db, document_id, use_cache=False)
    prompt = PROFILE_ENRICH_PROMPT.format(
        file_name=doc.file_name,
        context_block=_profile_context_block(chunks, doc),
    )
    try:
        raw = completion(
            messages=[{"role": "user", "content": prompt}],
            role=ModelRole.SLM,
            response_format={"type": "json_object"},
        )
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start < 0 or end <= start:
            return None
        data = json.loads(raw[start:end])
    except Exception as exc:
        logger.warning("profile enrich failed for %s: %s", document_id, exc)
        return None

    structure = dict(prior.structure)
    if data.get("column_roles"):
        structure["column_roles"] = data["column_roles"]
    if data.get("overview_facets"):
        structure["overview_facets"] = data["overview_facets"]

    profile = DocumentProfile(
        profile_version=prior.profile_version + 1,
        canonical_kind=str(data.get("canonical_kind") or prior.canonical_kind),
        kind_labels=list(data.get("kind_labels") or prior.kind_labels),
        structure=structure,
        synthesis_outline=list(data.get("synthesis_outline") or prior.synthesis_outline),
        anti_patterns=list(data.get("anti_patterns") or prior.anti_patterns),
        confidence=float(data.get("confidence") or 0.7),
        source="slm_enrich_v1",
        updated_at=utc_now_iso(),
        amplification_events=[*prior.amplification_events, "slm_enrich_v1"],
    )
    _upsert_profile_tag(db, document_id, profile)
    invalidate_profile_cache(document_id)
    return profile


def amplify_profile_from_coverage(
    db: Session,
    document_id: str,
    *,
    missing_facets: list[str],
) -> DocumentProfile | None:
    """Lightweight SLM patch when chat coverage reports gaps."""
    if not missing_facets or not llm_available():
        return None
    prior = load_profile(db, document_id, use_cache=False)
    prompt = (
        f"Document kind: {prior.canonical_kind}. "
        f"Add overview_facets JSON array entries for missing topics: {missing_facets}. "
        f"Existing facets: {json.dumps(prior.structure.get('overview_facets', []))}. "
        "Return JSON only: {{\"overview_facets\": [...]}}"
    )
    try:
        raw = completion(
            messages=[{"role": "user", "content": prompt}],
            role=ModelRole.SLM,
            response_format={"type": "json_object"},
        )
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end])
    except Exception:
        return None

    facets = list(prior.structure.get("overview_facets") or [])
    new_facets = list(data.get("overview_facets") or [])
    seen = {f.get("label") for f in facets if isinstance(f, dict)}
    for f in new_facets:
        if isinstance(f, dict) and f.get("label") not in seen:
            facets.append(f)
            seen.add(f.get("label"))

    structure = dict(prior.structure)
    structure["overview_facets"] = facets
    profile = DocumentProfile(
        profile_version=prior.profile_version + 1,
        canonical_kind=prior.canonical_kind,
        kind_labels=prior.kind_labels,
        structure=structure,
        synthesis_outline=prior.synthesis_outline,
        anti_patterns=prior.anti_patterns,
        confidence=prior.confidence,
        source="amplify_coverage",
        updated_at=utc_now_iso(),
        amplification_events=[*prior.amplification_events, f"coverage_gap:{','.join(missing_facets[:5])}"],
    )
    _upsert_profile_tag(db, document_id, profile)
    invalidate_profile_cache(document_id)
    return profile


def primary_unit_for_documents(profiles: dict[str, DocumentProfile]) -> str | None:
    units = [p.structure.get("primary_unit") for p in profiles.values() if p.structure.get("primary_unit")]
    if not units:
        return None
    if all(u == "table_row" for u in units):
        return "table_row"
    return units[0]


def merged_synthesis_outline(profiles: dict[str, DocumentProfile]) -> list[str]:
    for p in profiles.values():
        if p.synthesis_outline:
            return p.synthesis_outline
    return []


def is_litigation_profile(profile: DocumentProfile) -> bool:
    labels = " ".join(profile.kind_labels + [profile.canonical_kind]).casefold()
    return any(k in labels for k in ("litigation", "regulatory", "court", "complaint", "judgment", "commission"))


def amplify_profile_job(document_id: str, missing_facets: list[str]) -> None:
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        amplify_profile_from_coverage(db, document_id, missing_facets=missing_facets)
        db.commit()
    except Exception as exc:
        logger.warning("amplify_profile_job failed for %s: %s", document_id, exc)
        db.rollback()
    finally:
        db.close()
