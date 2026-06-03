from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

from app.config import settings
from app.services.document_context import DocumentContext
from app.services.model_router import ModelRole, completion
from app.services.query_understanding import SearchPass

logger = logging.getLogger(__name__)

_EXPANSION_PROMPT = """Generate {max_phrases} short keyword phrases to search a legal document index.
Return JSON only: {{"phrases": ["phrase one", "phrase two"]}}

Rules:
- Phrases should be synonyms, related legal terms, or alternate wordings for the question.
- Use vocabulary from document context when provided.
- Each phrase is 2-6 words; no full sentences.
- Do not repeat the exact user question.

User question: {query}
{doc_context}"""

_CACHE: dict[tuple[str, str], tuple[float, list[str]]] = {}


def _normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", (query or "").strip().casefold())


def _fts_safe_phrase(phrase: str) -> str:
    """Strip characters that break SQLite FTS5 MATCH syntax."""
    cleaned = re.sub(r"['\"*?:]", " ", phrase or "")
    return re.sub(r"\s+", " ", cleaned).strip()


def _cache_get(workspace_id: str | None, query: str) -> list[str] | None:
    key = (workspace_id or "", _normalize_query(query))
    entry = _CACHE.get(key)
    if not entry:
        return None
    ts, phrases = entry
    if time.monotonic() - ts > settings.query_expansion_cache_ttl_sec:
        _CACHE.pop(key, None)
        return None
    return list(phrases)


def _cache_set(workspace_id: str | None, query: str, phrases: list[str]) -> None:
    key = (workspace_id or "", _normalize_query(query))
    _CACHE[key] = (time.monotonic(), phrases[: settings.query_expansion_max_phrases])


@dataclass
class QueryExpansionResult:
    phrases: list[str]
    source: str  # slm | heuristic | cache | disabled


def expand_query(
    query: str,
    *,
    workspace_id: str | None = None,
    document_context: DocumentContext | None = None,
) -> QueryExpansionResult:
    """Produce expanded keyword phrases (paper q') for broad retrieval passes."""
    if not settings.enable_query_expansion:
        return QueryExpansionResult(phrases=[], source="disabled")

    cached = _cache_get(workspace_id, query)
    if cached is not None:
        return QueryExpansionResult(phrases=cached, source="cache")

    doc_block = ""
    if document_context:
        doc_block = document_context.to_prompt_block()

    raw = completion(
        messages=[{
            "role": "user",
            "content": _EXPANSION_PROMPT.format(
                max_phrases=settings.query_expansion_max_phrases,
                query=query,
                doc_context=doc_block,
            ),
        }],
        role=ModelRole.SLM,
        temperature=0.0,
        response_format={"type": "json_object"},
    )

    phrases: list[str] = []
    if raw:
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            data = json.loads(raw[start:end])
            for p in data.get("phrases") or []:
                s = str(p).strip()
                if s and s.casefold() != query.casefold():
                    safe = _fts_safe_phrase(s)
                    if safe:
                        phrases.append(safe)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("query expansion parse failed: %s", exc)

    if not phrases:
        phrases = _heuristic_phrases(query)

    phrases = phrases[: settings.query_expansion_max_phrases]
    _cache_set(workspace_id, query, phrases)
    return QueryExpansionResult(
        phrases=phrases,
        source="slm" if raw else "heuristic",
    )


def _heuristic_phrases(query: str) -> list[str]:
    """Rule-based synonyms when SLM unavailable."""
    q = query.casefold()
    out: list[str] = []
    pairs = [
        (r"liability\s+cap|cap\s+on\s+damages", ["limitation of liability", "liability cap"]),
        (r"damages?\s+(claimed|sought|sum)", ["relief sought", "monetary damages"]),
        (r"negligence", ["duty of care", "breach of duty"]),
        (r"plaintiff|claimant", ["defendant", "respondent"]),
        (r"termination|terminate", ["notice period", "expiry"]),
    ]
    for pattern, syns in pairs:
        if re.search(pattern, q):
            out.extend(syns)
    tokens = [t for t in re.findall(r"\w+", q) if len(t) > 3]
    if len(tokens) >= 2:
        out.append(" ".join(tokens[:4]))
    return [_fts_safe_phrase(p) for p in out[: settings.query_expansion_max_phrases] if _fts_safe_phrase(p)]


def expansion_search_passes(phrases: list[str]) -> list[SearchPass]:
    """Broad OR passes from expanded phrases (paper Step 1)."""
    if not phrases:
        return []
    passes: list[SearchPass] = []
    if len(phrases) >= 2:
        passes.append(
            SearchPass(
                label="expansion_broad",
                fts_terms=phrases,
                operator="OR",
                pin_best=False,
            )
        )
    for i, phrase in enumerate(phrases[:3]):
        passes.append(
            SearchPass(
                label=f"expansion_{i + 1}",
                fts_terms=[phrase],
                operator="OR",
                pin_best=False,
            )
        )
    return passes
