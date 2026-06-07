"""Dynamic claim-to-chunk binding via text similarity (no domain rules)."""

from __future__ import annotations

import re
from dataclasses import dataclass

_WORD_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_DIGIT_TOKEN_RE = re.compile(r"\d+")
_NUMBER_PHRASE_RE = re.compile(r"(\d+)\s+of\s+(\d+)", re.IGNORECASE)
_DATE_LITERAL_RE = re.compile(r"\d{1,2}[./]\d{1,2}[./]\d{2,4}")

OVERLAP_THRESHOLD = 0.25
REASSIGN_MARGIN = 0.15


@dataclass
class ChunkCandidate:
    chunk_id: str
    text: str
    index: int | None = None
    bbox: dict | None = None


def token_overlap_score(needle: str, haystack: str) -> float:
    a = {t.casefold() for t in _WORD_TOKEN_RE.findall(needle or "") if len(t) > 2}
    if not a:
        return 0.0
    b = {t.casefold() for t in _WORD_TOKEN_RE.findall(haystack or "") if len(t) > 2}
    return len(a & b) / len(a)


def _phrase_variants(d1: str, d2: str) -> list[str]:
    return [
        f"{d1} of {d2}",
        f"{d1}/{d2}",
        f"{d1} / {d2}",
    ]


def structured_literal_alignment(claim: str, chunk_text: str) -> float | None:
    """Alignment for co-occurring literals (N of M, dates). None = no structured literals."""
    claim_text = claim or ""
    chunk_cf = (chunk_text or "").casefold()
    phrase_groups = [
        [v.casefold() for v in _phrase_variants(m.group(1), m.group(2))]
        for m in _NUMBER_PHRASE_RE.finditer(claim_text)
    ]
    date_literals = [m.group(0).casefold() for m in _DATE_LITERAL_RE.finditer(claim_text)]
    required = len(phrase_groups) + len(date_literals)
    if required == 0:
        return None
    hits = sum(1 for variants in phrase_groups if any(v in chunk_cf for v in variants))
    hits += sum(1 for lit in date_literals if lit in chunk_cf)
    return hits / required


def numeric_token_alignment(claim: str, chunk_text: str) -> float:
    """Share of claim digit tokens (2+ digits) that appear in chunk text."""
    structured = structured_literal_alignment(claim, chunk_text)
    if structured is not None:
        return structured
    digits = [d for d in _DIGIT_TOKEN_RE.findall(claim or "") if len(d) >= 2]
    if not digits:
        return 1.0
    haystack = chunk_text or ""
    hits = sum(1 for d in digits if d in haystack)
    return hits / len(digits)


def score_claim_to_chunk(claim: str, chunk_text: str) -> float:
    needle = (claim or "").casefold().strip()
    haystack = (chunk_text or "").casefold()
    if len(needle) < 8:
        return 0.0
    for length in (120, 80, 50, 30):
        fragment = needle[:length]
        if len(fragment) < 8:
            continue
        if fragment in haystack:
            return 1.0
    # Try a middle fragment to avoid false matches on common sentence starts
    if len(needle) > 60:
        mid_frag = needle[len(needle)//2 - 25 : len(needle)//2 + 25]
        if len(mid_frag) >= 20 and mid_frag in haystack:
            return 0.95
    overlap = token_overlap_score(claim, chunk_text)
    num_align = numeric_token_alignment(claim, chunk_text)
    has_digits = bool(_DIGIT_TOKEN_RE.findall(claim))
    if has_digits and num_align < 1.0:
        return min(overlap, 0.2)
    if has_digits and num_align == 1.0:
        return max(overlap, 0.95)
    return overlap


def best_chunk_for_claim(
    claim: str,
    candidates: list[ChunkCandidate],
    *,
    min_score: float = OVERLAP_THRESHOLD,
) -> tuple[ChunkCandidate | None, float]:
    best: ChunkCandidate | None = None
    best_key: tuple[float, float, int] = (0.0, 0.0, 0)
    for candidate in candidates:
        score = score_claim_to_chunk(claim, candidate.text)
        num_align = numeric_token_alignment(claim, candidate.text)
        key = (score, num_align, -len(candidate.text or ""))
        if key > best_key:
            best_key = key
            best = candidate
    best_score = best_key[0] if best else 0.0
    if best is None or best_score < min_score:
        return None, 0.0
    return best, best_score


def ref_binding_surfaces(ref) -> list[ChunkCandidate]:
    """All bindable text surfaces on a citation ref (preview, anchors, page chunks)."""
    surfaces: list[ChunkCandidate] = []
    seen: set[str] = set()

    def _add(chunk_id: str, text: str, bbox: dict | None = None) -> None:
        key = f"{chunk_id}:{(text or '')[:48].casefold()}"
        if not text or key in seen:
            return
        seen.add(key)
        surfaces.append(
            ChunkCandidate(
                chunk_id=chunk_id,
                text=text,
                index=ref.index,
                bbox=bbox,
            )
        )

    if ref.preview:
        _add(ref.chunk_id, ref.preview, ref.bbox)
    for anchor in ref.sentence_anchors or []:
        if isinstance(anchor, dict):
            _add(
                anchor.get("chunk_id") or ref.chunk_id,
                anchor.get("sentence") or "",
                anchor.get("bbox"),
            )
    for chunk in ref.page_chunks or []:
        if isinstance(chunk, dict):
            _add(
                chunk.get("chunk_id") or ref.chunk_id,
                chunk.get("text") or "",
                chunk.get("bbox"),
            )
    return surfaces


def best_ref_index_for_claim(claim: str, refs: list) -> tuple[int | None, float]:
    """Return citation index with highest claim overlap across all ref surfaces."""
    candidates: list[ChunkCandidate] = []
    for ref in refs:
        candidates.extend(ref_binding_surfaces(ref))
    best, score = best_chunk_for_claim(claim, candidates)
    if best is None or best.index is None:
        return None, 0.0
    return best.index, score


def best_binding_for_claim(
    claim: str,
    refs: list,
) -> tuple[int | None, str | None, dict | None, float]:
    """Best (ref index, chunk_id, bbox) for a claim across all citation surfaces."""
    best: ChunkCandidate | None = None
    best_key: tuple[float, float, int] = (0.0, 0.0, 0)
    for ref in refs:
        for surface in ref_binding_surfaces(ref):
            score = score_claim_to_chunk(claim, surface.text)
            num_align = numeric_token_alignment(claim, surface.text)
            key = (score, num_align, -len(surface.text or ""))
            if key > best_key:
                best_key = key
                best = surface
    best_score = best_key[0] if best else 0.0
    if best is None or best.index is None or best_score < OVERLAP_THRESHOLD:
        return None, None, None, 0.0
    return best.index, best.chunk_id, best.bbox, best_score
