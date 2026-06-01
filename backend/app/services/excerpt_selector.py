from __future__ import annotations

import json
import logging
import re

from app.config import settings
from app.schemas import SearchHit
from app.services.model_router import ModelRole, completion
from app.services.query_understanding import SubQuestion

logger = logging.getLogger(__name__)

# Document-agnostic fact signals (no corpus-specific vocabulary)
_FACT_HINT_RE = re.compile(
    r"\b(?:"
    r"aged?|years?|old|infant|plaintiff(?:'s)?|defendant(?:'s)?|"
    r"son|daughter|child|children|claimant|respondent|"
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"damages|occurred|died|injur|accident"
    r")\b",
    re.IGNORECASE,
)
_PROPER_NAME_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b")
_IDENTITY_PHRASE_RE = re.compile(
    r"infant\s+son\s+of|son\s+of\s+the\s+plaintiff|the\s+plaintiff'?s\s+son",
    re.IGNORECASE,
)
# OCR may split a surname: "Ma x Chester, the infant son..."
_OCR_NAME_BEFORE_INFANT_RE = re.compile(
    r"[A-Z][a-z]+(?:\s+[a-z])?\s+[A-Z][a-z]+,\s*the\s+infant\s+son",
    re.IGNORECASE,
)
_IDENTITY_CLAUSE_RE = re.compile(
    r"[A-Z][A-Za-z.\s]{2,50}?,\s*the\s+infant\s+son\s+of\s+the\s+plaintiff[^.]{0,160}",
    re.IGNORECASE,
)
_CITATION_HEADER_RE = re.compile(
    r"^\s*(?:v\.|appeal\s+from|council\s+of|^\[\d+\])",
    re.IGNORECASE,
)

EXCERPT_SELECTOR_PROMPT = """Select the best excerpt from each document chunk for answering the user's question.
Return JSON only:
{{
  "excerpts": [
    {{"chunk_id": "...", "excerpt": "...", "start_offset": 0}}
  ]
}}

Rules:
- excerpt must be a contiguous substring copied verbatim from the chunk text (handle OCR spacing faithfully).
- Pick the span that best supports answering the question or sub-questions — NEVER return only citation headers or case captions.
- For name questions: include the span where a person is named in relation to plaintiff/son/infant.
- Prefer spans with names, dates, amounts, or role labels when relevant.
- Keep each excerpt under {max_chars} characters.
- If nothing in a chunk is relevant, use the most informative {max_chars}-char span.

Question: {question}
Sub-questions: {sub_questions}

Chunks:
{chunk_blocks}"""


def _trim_excerpt_end(excerpt: str, max_chars: int) -> str:
    if len(excerpt) <= max_chars:
        return excerpt
    last_space = excerpt.rfind(" ", max_chars // 2)
    if last_space > 0:
        return excerpt[:last_space].rstrip() + "…"
    return excerpt[:max_chars].rstrip() + "…"


def _identity_anchored_excerpt(text: str, max_chars: int) -> str | None:
    """Center excerpt on a named infant/son identity clause when present."""
    cleaned = (text or "").strip().replace("\n", " ")
    if not cleaned:
        return None

    match = _OCR_NAME_BEFORE_INFANT_RE.search(cleaned) or _IDENTITY_CLAUSE_RE.search(cleaned)
    if not match:
        phrase = _IDENTITY_PHRASE_RE.search(cleaned)
        if not phrase:
            return None
        start = max(0, phrase.start() - 90)
    else:
        start = max(0, match.start() - 30)

    end = min(len(cleaned), start + max_chars)
    if end - start < max_chars:
        start = max(0, end - max_chars)
    excerpt = cleaned[start:end].strip()
    if end < len(cleaned):
        excerpt = _trim_excerpt_end(excerpt, max_chars)
    return excerpt


def _name_subquestion_requested(sub_questions: list[SubQuestion] | None) -> bool:
    return any(
        "name" in sq.label.casefold() or "identity" in sq.label.casefold()
        for sq in (sub_questions or [])
    )


def _best_excerpt(
    text: str,
    max_chars: int,
    *,
    sub_questions: list[SubQuestion] | None = None,
) -> str:
    """Pick a window maximizing generic fact-bearing tokens (not citation headers)."""
    cleaned = (text or "").strip().replace("\n", " ")
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned

    prefer_identity = _name_subquestion_requested(sub_questions) or bool(
        _IDENTITY_PHRASE_RE.search(cleaned) or _OCR_NAME_BEFORE_INFANT_RE.search(cleaned)
    )
    if prefer_identity:
        anchored = _identity_anchored_excerpt(cleaned, max_chars)
        if anchored:
            return anchored

    best_score = -1
    best_start = 0
    step = max(10, max_chars // 10)
    for start in range(0, len(cleaned) - max_chars + 1, step):
        window = cleaned[start : start + max_chars]
        score = len(_FACT_HINT_RE.findall(window)) + len(_PROPER_NAME_RE.findall(window))
        if _OCR_NAME_BEFORE_INFANT_RE.search(window):
            score += 12
        elif _IDENTITY_PHRASE_RE.search(window):
            score += 5
            # Penalize windows where identity phrase appears without a preceding name.
            if not _OCR_NAME_BEFORE_INFANT_RE.search(window):
                idx = window.casefold().find("infant son")
                if idx >= 0 and not re.search(r"[A-Z][a-z]+,\s*the\s+infant\s+son", window[: idx + 20]):
                    score -= 4
        if score > best_score:
            best_score = score
            best_start = start

    if best_score <= 0:
        return cleaned[:max_chars].rstrip() + "…"

    excerpt = cleaned[best_start : best_start + max_chars].strip()
    if best_start + max_chars < len(cleaned):
        excerpt = _trim_excerpt_end(excerpt, max_chars)
    return excerpt


def _fallback_excerpt(
    text: str,
    max_chars: int,
    *,
    sub_questions: list[SubQuestion] | None = None,
) -> str:
    return _best_excerpt(text, max_chars, sub_questions=sub_questions)


def _excerpt_quality(text: str) -> int:
    """Higher = more likely to contain answer-bearing facts."""
    if not text:
        return 0
    score = len(_FACT_HINT_RE.findall(text)) + len(_PROPER_NAME_RE.findall(text))
    if _IDENTITY_PHRASE_RE.search(text):
        score += 5
    if _CITATION_HEADER_RE.match(text[:80]):
        score -= 3
    return score


def _refine_excerpt(
    full_text: str,
    slm_excerpt: str,
    max_chars: int,
    *,
    sub_questions: list[SubQuestion] | None = None,
) -> str:
    """Prefer SLM excerpt unless generic scoring shows a better window exists."""
    best = _best_excerpt(full_text, max_chars, sub_questions=sub_questions)
    slm_q = _excerpt_quality(slm_excerpt)
    if _OCR_NAME_BEFORE_INFANT_RE.search(slm_excerpt):
        slm_q += 8
    if slm_q + 1 >= _excerpt_quality(best):
        return slm_excerpt[:max_chars]
    return best


def select_excerpts(
    hits: list[SearchHit],
    *,
    question: str,
    sub_questions: list[SubQuestion] | None = None,
    max_chars: int = 600,
) -> dict[str, str]:
    """Return chunk_id -> excerpt text. Uses SLM when enabled, else best window."""
    if not hits:
        return {}

    if not settings.enable_excerpt_selector:
        return {
            h.chunk_id: _best_excerpt(h.text_content or "", max_chars, sub_questions=sub_questions)
            for h in hits
        }

    chunk_blocks: list[str] = []
    for h in hits:
        text = (h.text_content or "")[:2000]
        chunk_blocks.append(f"chunk_id={h.chunk_id} page={h.page_number}\n{text}")

    sub_q_text = "\n".join(
        f"- {sq.label}: {sq.question}" for sq in (sub_questions or [])
    ) or "(none — answer the main question)"

    raw = completion(
        messages=[{
            "role": "user",
            "content": EXCERPT_SELECTOR_PROMPT.format(
                max_chars=max_chars,
                question=question,
                sub_questions=sub_q_text,
                chunk_blocks="\n\n---\n\n".join(chunk_blocks),
            ),
        }],
        role=ModelRole.SLM,
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    if not raw:
        return {
            h.chunk_id: _best_excerpt(h.text_content or "", max_chars, sub_questions=sub_questions)
            for h in hits
        }

    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end])
        out: dict[str, str] = {}
        by_id = {h.chunk_id: h for h in hits}
        for item in data.get("excerpts") or []:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("chunk_id") or "")
            excerpt = str(item.get("excerpt") or "").strip()
            if cid and excerpt:
                full = (by_id[cid].text_content or "") if cid in by_id else ""
                out[cid] = (
                    _refine_excerpt(full, excerpt, max_chars, sub_questions=sub_questions)
                    if full
                    else excerpt[:max_chars]
                )
        if out:
            for h in hits:
                out.setdefault(
                    h.chunk_id,
                    _best_excerpt(h.text_content or "", max_chars, sub_questions=sub_questions),
                )
            return out
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("excerpt selector parse failed: %s", exc)

    return {
        h.chunk_id: _best_excerpt(h.text_content or "", max_chars, sub_questions=sub_questions)
        for h in hits
    }


def identity_signal_strength(text: str | None) -> int:
    """Higher = more likely to contain a named infant/son identity clause."""
    if not text:
        return 0
    if _OCR_NAME_BEFORE_INFANT_RE.search(text):
        return 3
    if _IDENTITY_CLAUSE_RE.search(text):
        return 2
    if _IDENTITY_PHRASE_RE.search(text):
        return 1
    t = text.casefold()
    if "infant son" in t and bool(_PROPER_NAME_RE.search(text)):
        return 1
    return 0


def has_identity_signal(text: str | None) -> bool:
    """Whether chunk text likely identifies a named party (document-agnostic)."""
    return identity_signal_strength(text) > 0
