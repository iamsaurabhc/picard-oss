"""Demand-driven retrieval depth — budgets scale from query demand, not latency profile."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.config import settings
from app.services.query_understanding import QueryUnderstanding

DepthTier = Literal["pinpoint", "standard", "deep", "exhaustive"]

_EXPLICIT_DEPTH_PHRASES = (
    "in depth",
    "in-depth",
    "comprehensive",
    "significant",
    "thorough",
    "detailed",
)
_STRUCTURED_ASK_PHRASES = (
    "procedural history",
    "sections",
    "section",
    "context",
    "dates",
)


@dataclass(frozen=True)
class RetrievalDepthPolicy:
    depth_tier: DepthTier
    top_k: int
    pool_k: int
    max_pages: int
    prompt_excerpt_cap: int
    gap_fill_rounds: int
    max_chars_per_page: int
    demand_signals: tuple[str, ...]


def infer_depth_demand(
    query: str,
    understanding: QueryUnderstanding,
) -> tuple[DepthTier, list[str]]:
    """Infer depth tier and human-readable demand signals from query + understanding."""
    q = query.casefold()
    signals: list[str] = []

    for phrase in _EXPLICIT_DEPTH_PHRASES:
        if phrase in q:
            signals.append(f"explicit:{phrase.replace(' ', '_').replace('-', '_')}")

    for phrase in _STRUCTURED_ASK_PHRASES:
        if phrase in q:
            signals.append(f"explicit:{phrase.replace(' ', '_')}")

    if understanding.intent == "case_overview":
        signals.append("intent:case_overview")

    if len(understanding.sub_questions) >= 3:
        signals.append(f"sub_questions:{len(understanding.sub_questions)}")

    if understanding.coverage_goal == "broad matter summary":
        signals.append("coverage:broad_matter_summary")

    if understanding.require_dates_facet or (
        "date" in q and any(w in q for w in ("dates", "date", "procedural history", "timeline"))
    ):
        signals.append("explicit:dates")

    if query.count("?") >= 2:
        signals.append("multi_part:questions")

    explicit_depth = any(s.startswith("explicit:detailed") or s.startswith("explicit:comprehensive") for s in signals)
    has_dates = "explicit:dates" in signals
    has_sections = any(s.startswith("explicit:sections") or s == "explicit:context" for s in signals)

    if understanding.intent == "factual_lookup" and understanding.coverage_goal == "pinpoint fact":
        return "pinpoint", signals

    if explicit_depth and (has_dates or has_sections):
        return "exhaustive", signals

    if understanding.intent == "case_overview" and has_dates and (explicit_depth or has_sections):
        return "exhaustive", signals

    if understanding.intent == "case_overview":
        if explicit_depth or len(signals) >= 4:
            return "exhaustive", signals
        return "deep", signals

    if len(understanding.sub_questions) >= 3:
        return "deep", signals

    if understanding.coverage_goal == "broad matter summary":
        return "deep", signals

    return "standard", signals


def resolve_retrieval_depth(
    query: str,
    understanding: QueryUnderstanding,
    *,
    is_overview: bool = False,
    is_listing: bool = False,
) -> RetrievalDepthPolicy:
    tier, signals = infer_depth_demand(query, understanding)
    if understanding.depth_demand:
        tier = understanding.depth_demand
        signals = [*signals, f"planner:{understanding.depth_demand}"]

    if is_listing:
        return RetrievalDepthPolicy(
            depth_tier="deep",
            top_k=settings.chat_listing_top_k,
            pool_k=settings.chat_listing_pool_k,
            max_pages=settings.listing_max_pages_per_doc,
            prompt_excerpt_cap=settings.chat_listing_map_excerpt_chars,
            gap_fill_rounds=1,
            max_chars_per_page=settings.listing_max_chars_per_page,
            demand_signals=tuple(signals),
        )

    tier_budgets: dict[DepthTier, tuple[int, int, int, int, int]] = {
        "pinpoint": (12, settings.chat_retrieval_pool_k, 3, 600, 1),
        "standard": (settings.chat_top_k, settings.chat_retrieval_pool_k, 6, 500, 1),
        "deep": (
            settings.chat_overview_top_k,
            settings.chat_overview_pool_k,
            10,
            1500,
            2,
        ),
        "exhaustive": (
            24,
            max(settings.chat_overview_pool_k, 48),
            12,
            1800,
            3,
        ),
    }
    top_k, pool_k, max_pages, excerpt_cap, gap_rounds = tier_budgets[tier]

    if is_overview:
        max_chars = settings.listing_max_chars_per_page
        if tier in ("deep", "exhaustive"):
            excerpt_cap = max(excerpt_cap, min(settings.overview_excerpt_chars, 1800))
    else:
        max_chars = settings.overview_excerpt_chars if tier in ("deep", "exhaustive") else 800

    return RetrievalDepthPolicy(
        depth_tier=tier,
        top_k=top_k,
        pool_k=pool_k,
        max_pages=max_pages,
        prompt_excerpt_cap=excerpt_cap,
        gap_fill_rounds=gap_rounds,
        max_chars_per_page=max_chars,
        demand_signals=tuple(signals),
    )


def depth_policy_to_diagnostics(policy: RetrievalDepthPolicy) -> dict:
    return {
        "depth_tier": policy.depth_tier,
        "demand_signals": list(policy.demand_signals),
        "top_k": policy.top_k,
        "pool_k": policy.pool_k,
        "max_pages": policy.max_pages,
        "prompt_excerpt_cap": policy.prompt_excerpt_cap,
        "gap_fill_rounds": policy.gap_fill_rounds,
    }
