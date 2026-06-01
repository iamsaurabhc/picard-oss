from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.query_understanding import FtsPlan


def build_fts_match_string(plan: FtsPlan, *, raw_query_fallback: str = "") -> str:
    """Map structured FTS plan to an FTS5 MATCH string (deterministic, no heuristics)."""
    groups: list[str] = []

    for phrase in plan.phrases:
        cleaned = " ".join(phrase.split())
        if cleaned:
            groups.append(f'"{cleaned}"')

    if plan.must_terms:
        if plan.operator == "AND":
            groups.append(" ".join(plan.must_terms))
        else:
            groups.extend(plan.must_terms)

    if plan.should_terms:
        if plan.operator == "OR":
            groups.extend(plan.should_terms)
        elif plan.operator == "AND":
            # Optional should terms: OR-group appended as one AND operand
            groups.append(" OR ".join(plan.should_terms))

    if not groups:
        return raw_query_fallback.strip()

    if plan.operator == "AND":
        # Token AND is more robust than strict quoted phrases for case names (v. variants).
        if plan.must_terms:
            return " ".join(plan.must_terms)
        return " ".join(groups)
    return " OR ".join(groups)
