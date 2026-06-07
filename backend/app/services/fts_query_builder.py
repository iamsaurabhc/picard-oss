from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.query_understanding import FtsPlan


def build_fts_match_string(plan: FtsPlan, *, raw_query_fallback: str = "") -> str:
    """Map structured FTS plan to an FTS5 MATCH string (deterministic, no heuristics)."""

    def _safe(text: str) -> str:
        # Wrap in quotes to prevent FTS5 syntax errors on punctuation like '.' or '-'
        clean = " ".join(text.split()).replace('"', '')
        return f'"{clean}"' if clean else ""

    groups: list[str] = []

    for phrase in plan.phrases:
        safe_phrase = _safe(phrase)
        if safe_phrase:
            groups.append(safe_phrase)

    if plan.must_terms:
        quoted_must = [q for t in plan.must_terms if (q := _safe(t))]
        if plan.operator == "AND":
            groups.append(" ".join(quoted_must))
        else:
            groups.extend(quoted_must)

    if plan.should_terms:
        quoted_should = [q for t in plan.should_terms if (q := _safe(t))]
        if plan.operator == "OR":
            groups.extend(quoted_should)
        elif plan.operator == "AND":
            if quoted_should:
                groups.append(" OR ".join(quoted_should))

    if not groups:
        if not raw_query_fallback.strip():
            return ""
        return _safe(raw_query_fallback)

    if plan.operator == "AND":
        if plan.must_terms:
            quoted_must = [q for t in plan.must_terms if (q := _safe(t))]
            return " ".join(quoted_must)
        return " ".join(groups)
    return " OR ".join(groups)

