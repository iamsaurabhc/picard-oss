"""Chat latency profile — toggles SLM-heavy steps for balanced vs quality paths."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from app.config import settings


@dataclass(frozen=True)
class LatencyProfileFlags:
    enable_context_ranker: bool
    enable_excerpt_selector: bool
    enable_query_expansion: bool
    query_planner_repair_on_zero_hits: bool
    listing_map_reduce_min_docs: int
    chat_listing_map_max_docs: int
    use_fast_tier_synthesis: bool
    defer_page_vectors: bool


def resolve_latency_profile(profile: str | None = None) -> LatencyProfileFlags:
    name = (profile or settings.chat_latency_profile or "balanced").strip().lower()
    if name == "quality":
        return LatencyProfileFlags(
            enable_context_ranker=True,
            enable_excerpt_selector=True,
            enable_query_expansion=True,
            query_planner_repair_on_zero_hits=True,
            listing_map_reduce_min_docs=settings.listing_map_reduce_min_docs,
            chat_listing_map_max_docs=settings.chat_listing_map_max_docs,
            use_fast_tier_synthesis=False,
            defer_page_vectors=False,
        )
    if name == "fast":
        return LatencyProfileFlags(
            enable_context_ranker=False,
            enable_excerpt_selector=False,
            enable_query_expansion=False,
            query_planner_repair_on_zero_hits=False,
            listing_map_reduce_min_docs=max(settings.listing_map_reduce_min_docs, 8),
            chat_listing_map_max_docs=min(settings.chat_listing_map_max_docs, 4),
            use_fast_tier_synthesis=True,
            defer_page_vectors=True,
        )
    # balanced (default)
    return LatencyProfileFlags(
        enable_context_ranker=False,
        enable_excerpt_selector=False,
        enable_query_expansion=False,
        query_planner_repair_on_zero_hits=False,
        listing_map_reduce_min_docs=max(settings.listing_map_reduce_min_docs, 8),
        chat_listing_map_max_docs=min(settings.chat_listing_map_max_docs, 6),
        use_fast_tier_synthesis=True,
        defer_page_vectors=False,
    )


@contextmanager
def apply_latency_profile(profile: str | None = None) -> Iterator[LatencyProfileFlags]:
    """Temporarily override settings for the active latency profile."""
    flags = resolve_latency_profile(profile)
    saved = {
        "enable_context_ranker": settings.enable_context_ranker,
        "enable_excerpt_selector": settings.enable_excerpt_selector,
        "enable_query_expansion": settings.enable_query_expansion,
        "query_planner_repair_on_zero_hits": settings.query_planner_repair_on_zero_hits,
        "listing_map_reduce_min_docs": settings.listing_map_reduce_min_docs,
        "chat_listing_map_max_docs": settings.chat_listing_map_max_docs,
    }
    settings.enable_context_ranker = flags.enable_context_ranker
    settings.enable_excerpt_selector = flags.enable_excerpt_selector
    settings.enable_query_expansion = flags.enable_query_expansion
    settings.query_planner_repair_on_zero_hits = flags.query_planner_repair_on_zero_hits
    settings.listing_map_reduce_min_docs = flags.listing_map_reduce_min_docs
    settings.chat_listing_map_max_docs = flags.chat_listing_map_max_docs
    try:
        yield flags
    finally:
        for key, val in saved.items():
            setattr(settings, key, val)
