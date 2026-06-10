from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings


@dataclass
class FtsHit:
    chunk_id: str
    document_id: str
    page_number: int
    text_content: str
    heading_path: str | None
    section_key: str | None
    bbox_json: str
    score: float
    chunk_type: str | None = None
    anchor_json: str | None = None


FTS_SPECIAL = re.compile(r'[*?:\()"\'\\.\-]')
STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "did",
        "do",
        "for",
        "how",
        "in",
        "is",
        "of",
        "or",
        "the",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "list",
        "all",
        "any",
        "involving",
        "about",
        "regarding",
        "concerning",
        "details",
        "detail",
        "show",
        "find",
        "give",
        "tell",
        "explain",
        "describe",
    }
)

_FTS_OR_TOKEN_THRESHOLD = 3
_EXPANSION_FILLER = frozenset({"v", "vs", "versus", "against", "between"})
_MIN_INFORMATIVE_CHUNK_CHARS = 40


def _extract_tokens(text: str) -> list[str]:
    q = re.sub(r"(?<=\d),(?=\d)", "", text)
    q = FTS_SPECIAL.sub(" ", q.replace('"', " "))
    tokens = re.findall(r"[\w£$]+", q, re.UNICODE)
    return [
        t
        for t in tokens
        if t.casefold() not in STOPWORDS
        and len(t) > 1
        and not t.startswith("£")
        and not (t.isdigit() and len(t) >= 3)
    ]


def _dedupe_tokens(tokens: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        key = t.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def _chunk_is_informative(text: str) -> bool:
    return len((text or "").strip()) >= _MIN_INFORMATIVE_CHUNK_CHARS


def _sanitize_fts_query(query: str) -> str:
    """Legacy sanitizer for raw query strings (CARP page-scoped search)."""
    phrase_groups: list[str] = []
    for match in re.finditer(r'"([^"]+)"', query):
        phrase_tokens = _dedupe_tokens(_extract_tokens(match.group(1)))
        if phrase_tokens:
            phrase_groups.append(" ".join(phrase_tokens[:8]))

    remainder = re.sub(r'"[^"]*"', " ", query)
    kept = _dedupe_tokens(_extract_tokens(remainder))
    substantive = [t for t in kept if t.casefold() not in _EXPANSION_FILLER]

    if phrase_groups:
        if len(phrase_groups) == 1:
            return phrase_groups[0]
        return " OR ".join(phrase_groups)

    if not substantive:
        return " ".join(kept) if kept else query.strip()

    if 2 <= len(substantive) <= 4 and (
        len(kept) > len(substantive) or len(substantive) <= _FTS_OR_TOKEN_THRESHOLD
    ):
        return " ".join(substantive)

    if len(substantive) > _FTS_OR_TOKEN_THRESHOLD:
        return " OR ".join(substantive)

    return " ".join(substantive)


def fts_discover_documents(
    db: Session,
    *,
    fts_query: str,
    workspace_id: str,
    document_ids: list[str] | None = None,
    limit: int = 64,
) -> list[tuple[str, int]]:
    """Distinct documents with chunk hits for an FTS query, ordered by hit count."""
    if not fts_query or not fts_query.strip():
        return []

    sql_parts = [
        """
        SELECT c.document_id, COUNT(*) AS hit_count
        FROM chunks_fts
        JOIN chunks c ON c.rowid = chunks_fts.rowid
        JOIN documents d ON d.id = c.document_id
        WHERE chunks_fts MATCH :q
          AND d.workspace_id = :ws
        """,
    ]
    params: dict = {"q": fts_query, "ws": workspace_id, "limit": limit}

    if document_ids:
        placeholders = ", ".join(f":doc_{i}" for i in range(len(document_ids)))
        sql_parts.append(f"AND c.document_id IN ({placeholders})")
        for i, doc_id in enumerate(document_ids):
            params[f"doc_{i}"] = doc_id

    sql_parts.append(
        "GROUP BY c.document_id ORDER BY hit_count DESC LIMIT :limit"
    )
    stmt = text("".join(sql_parts))
    rows = db.execute(stmt, params).mappings().all()
    return [(row["document_id"], int(row["hit_count"])) for row in rows]


def fts_search(
    db: Session,
    *,
    query: str,
    workspace_id: str,
    document_ids: list[str] | None = None,
    top_k: int = 12,
    min_score: float | None = None,
    max_chunks_per_doc: int | None = None,
    fts_query: str | None = None,
) -> list[FtsHit]:
    min_score = settings.fts_min_score if min_score is None else min_score
    max_chunks_per_doc = settings.fts_max_chunks_per_doc if max_chunks_per_doc is None else max_chunks_per_doc
    match_query = fts_query if fts_query is not None else _sanitize_fts_query(query)

    sql_parts = [
        """
        SELECT c.id, c.document_id, c.page_number, c.text_content, c.heading_path,
               c.section_key, c.bbox_json, c.chunk_type, c.anchor_json,
               bm25(chunks_fts) AS score
        FROM chunks_fts
        JOIN chunks c ON c.rowid = chunks_fts.rowid
        JOIN documents d ON d.id = c.document_id
        WHERE chunks_fts MATCH :q
          AND d.workspace_id = :ws
        """,
    ]
    params: dict = {"q": match_query, "ws": workspace_id, "limit": top_k * 4}

    if document_ids:
        placeholders = ", ".join(f":doc_{i}" for i in range(len(document_ids)))
        sql_parts.append(f"AND c.document_id IN ({placeholders})")
        for i, doc_id in enumerate(document_ids):
            params[f"doc_{i}"] = doc_id

    sql_parts.append("ORDER BY score LIMIT :limit")
    stmt = text("".join(sql_parts))
    rows = db.execute(stmt, params).mappings().all()

    hits: list[FtsHit] = []
    per_doc: dict[str, int] = {}
    for row in rows:
        if not _chunk_is_informative(row["text_content"]):
            continue
        score = float(row["score"])
        if score < min_score:
            continue
        doc_id = row["document_id"]
        if per_doc.get(doc_id, 0) >= max_chunks_per_doc:
            continue
        per_doc[doc_id] = per_doc.get(doc_id, 0) + 1
        hits.append(
            FtsHit(
                chunk_id=row["id"],
                document_id=doc_id,
                page_number=row["page_number"],
                text_content=row["text_content"],
                heading_path=row["heading_path"],
                section_key=row["section_key"],
                bbox_json=row["bbox_json"],
                score=score,
                chunk_type=row.get("chunk_type"),
                anchor_json=row.get("anchor_json"),
            )
        )
        if len(hits) >= top_k:
            break
    return hits


def fts_search_on_pages(
    db: Session,
    *,
    query: str,
    workspace_id: str,
    pages: set[tuple[str, int]],
    top_k: int = 40,
) -> list[FtsHit]:
    if not pages:
        return []
    fts_query = _sanitize_fts_query(query)
    hits: list[FtsHit] = []
    for document_id, page_number in sorted(pages):
        rows = db.execute(
            text(
                """
                SELECT c.id, c.document_id, c.page_number, c.text_content, c.heading_path,
                       c.section_key, c.bbox_json, c.chunk_type, c.anchor_json,
                       bm25(chunks_fts) AS score
                FROM chunks_fts
                JOIN chunks c ON c.rowid = chunks_fts.rowid
                JOIN documents d ON d.id = c.document_id
                WHERE chunks_fts MATCH :q
                  AND d.workspace_id = :ws
                  AND c.document_id = :doc_id
                  AND c.page_number = :page
                ORDER BY score
                """
            ),
            {"q": fts_query, "ws": workspace_id, "doc_id": document_id, "page": page_number},
        ).mappings().all()
        for row in rows:
            hits.append(
                FtsHit(
                    chunk_id=row["id"],
                    document_id=row["document_id"],
                    page_number=row["page_number"],
                    text_content=row["text_content"],
                    heading_path=row["heading_path"],
                    section_key=row["section_key"],
                    bbox_json=row["bbox_json"],
                    score=float(row["score"]),
                    chunk_type=row.get("chunk_type"),
                    anchor_json=row.get("anchor_json"),
                )
            )
    hits.sort(key=lambda h: h.score)
    return hits[:top_k]


def parse_bbox(bbox_json: str) -> dict:
    try:
        return json.loads(bbox_json)
    except json.JSONDecodeError:
        return {}
