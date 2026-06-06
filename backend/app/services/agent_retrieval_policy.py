"""Persona + breadth policy for Agent mode corpus retrieval (kernel-first)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.config import settings
from app.services.query_understanding import QueryUnderstanding, understand_query

Breadth = Literal["catalog", "matter_deep", "pinpoint"]
AgentProfile = Literal["firm", "court"]


@dataclass(frozen=True)
class RetrievalPolicy:
    breadth: Breadth
    agent_profile: str
    discovery_limit: int
    map_max_docs: int
    map_chunks_per_doc: int
    map_excerpt_chars: int
    listing_top_k: int
    synthesis_mode: str
    coverage_goal: str
    intent_override: str | None = None
    documents_in_scope: int = 0


_CATALOG_HINTS = re.compile(
    r"\b(?:list\s+all|all\s+(?:cases|matters|documents)|cases\s+(?:against|involving)|"
    r"case\s+details?\s+(?:against|involving)|matters\s+involving)\b",
    re.IGNORECASE,
)


def is_catalog_query(query: str, understanding: QueryUnderstanding | None = None) -> bool:
    """Catalog breadth from query phrasing — overrides LLM case_overview misroutes."""
    from app.services.query_understanding import _is_entity_matter_listing_query

    if _is_entity_matter_listing_query(query):
        return True
    if _CATALOG_HINTS.search(query):
        return True
    if understanding and understanding.intent == "entity_matter_listing":
        return True
    return False


def _normalize_profile(profile: str | None) -> AgentProfile:
    p = (profile or settings.agent_profile or "firm").casefold()
    return "court" if p == "court" else "firm"


def resolve_breadth(
    query: str,
    understanding: QueryUnderstanding,
    *,
    document_ids: list[str] | None,
) -> Breadth:
    scoped = len(document_ids or [])
    intent = understanding.intent

    if is_catalog_query(query, understanding):
        return "catalog"
    if intent == "factual_lookup":
        return "pinpoint"
    if intent == "case_overview":
        return "matter_deep"
    if scoped == 1:
        return "matter_deep"
    if scoped >= 2:
        return "catalog"
    return "matter_deep"


def build_agent_retrieval_policy(
    query: str,
    *,
    agent_profile: str | None = None,
    document_ids: list[str] | None = None,
    understanding: QueryUnderstanding | None = None,
    db=None,
    workspace_id: str | None = None,
) -> RetrievalPolicy:
    """Build retrieval policy from query, persona, and optional pre-computed understanding."""
    profile = _normalize_profile(agent_profile)
    u = understanding or understand_query(
        query,
        db=db,
        workspace_id=workspace_id,
        document_ids=document_ids,
    )
    breadth = resolve_breadth(query, u, document_ids=document_ids)

    intent_override: str | None = None
    if breadth == "catalog":
        intent_override = "entity_matter_listing"
    elif breadth == "matter_deep" and u.intent == "entity_matter_listing" and len(document_ids or []) <= 1:
        intent_override = "case_overview"

    if profile == "court":
        discovery = settings.court_agent_listing_discovery_doc_limit
        map_max = settings.court_agent_listing_map_max_docs
        coverage = (
            "Neutral per-document procedural listing; cite only what excerpts state."
            if breadth == "catalog"
            else "Neutral broad matter summary; no outcome prediction; cite only stated facts."
        )
    else:
        discovery = settings.firm_agent_listing_discovery_doc_limit
        map_max = settings.firm_agent_listing_map_max_docs
        coverage = (
            "Per-document matter catalog with parties, forum, case numbers, allegations, and outcomes when present."
            if breadth == "catalog"
            else "Broad matter summary covering parties, facts, damages, dates, and outcome when present in sources."
        )

    scoped = len(document_ids or [])
    if scoped >= 2:
        map_max = min(map_max, scoped)

    return RetrievalPolicy(
        breadth=breadth,
        agent_profile=profile,
        discovery_limit=discovery,
        map_max_docs=map_max,
        map_chunks_per_doc=settings.agent_listing_map_chunks_per_doc,
        map_excerpt_chars=settings.agent_listing_map_excerpt_chars,
        listing_top_k=settings.agent_listing_top_k,
        synthesis_mode="agent",
        coverage_goal=coverage,
        intent_override=intent_override,
        documents_in_scope=scoped,
    )


def apply_policy_to_understanding(
    understanding: QueryUnderstanding,
    policy: RetrievalPolicy,
    *,
    query: str = "",
    db=None,
    workspace_id: str | None = None,
    document_ids: list[str] | None = None,
) -> QueryUnderstanding:
    if policy.intent_override and understanding.intent != policy.intent_override:
        understanding.intent = policy.intent_override  # type: ignore[assignment]
    if policy.breadth == "catalog":
        understanding.intent = "entity_matter_listing"  # type: ignore[assignment]
        understanding.retrieval_mode = "SIMPLE"
        from app.services.query_understanding import _apply_listing_fields

        understanding = _apply_listing_fields(
            understanding,
            query,
            db=db,
            workspace_id=workspace_id,
        )
    if policy.coverage_goal:
        understanding.coverage_goal = policy.coverage_goal
    return understanding


def routing_flags_from_policy(
    policy: RetrievalPolicy | None,
    understanding: QueryUnderstanding,
) -> tuple[bool, bool]:
    """Return (is_listing, is_overview) from policy breadth when agent mode."""
    if policy is None:
        return (
            understanding.intent == "entity_matter_listing",
            understanding.intent == "case_overview",
        )
    if policy.breadth == "catalog":
        return True, False
    if policy.breadth == "matter_deep":
        return False, True
    return False, False
