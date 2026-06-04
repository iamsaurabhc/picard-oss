from __future__ import annotations

from typing import Literal

PicardAgentRole = Literal[
    "research",
    "tabular",
    "writer",
    "web",
    "compliance",
    "coordinator",
]

PICARD_AGENT_ROLES: frozenset[str] = frozenset(
    {"research", "tabular", "writer", "web", "compliance", "coordinator"}
)

# Roles that need later product phases to execute (validation warns, does not fail).
ROLE_PHASE_HINTS: dict[str, str] = {
    "writer": "Phase 8",
    "web": "Phase 9",
}

ROLE_REGISTRY: dict[str, dict[str, str | int]] = {
    "research": {"phase": 7, "label": "Corpus research"},
    "tabular": {"phase": 7, "label": "Tabular extract"},
    "writer": {"phase": 8, "label": "Template writer"},
    "web": {"phase": 9, "label": "Web fetch"},
    "compliance": {"phase": 7, "label": "Compliance checklist"},
    "coordinator": {"phase": 7, "label": "Merge coordinator"},
}

QUERY_INTENTS: frozenset[str] = frozenset(
    {
        "case_overview",
        "entity_matter_listing",
        "case_context",
        "timeline",
        "obligations",
        "factual_lookup",
        "general",
    }
)
