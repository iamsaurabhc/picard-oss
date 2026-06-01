from __future__ import annotations

from dataclasses import dataclass, field

from app.services.query_understanding import (
    Intent,
    QueryUnderstanding,
    RetrievalMode,
    understand_query,
)


@dataclass
class Constraint:
    type: str
    canonical: str
    surfaces: list[str] = field(default_factory=list)


@dataclass
class PlannerResult:
    mode: RetrievalMode
    constraints: list[Constraint]
    intent: Intent
    confidence: float
    used_slm: bool = False
    understanding: QueryUnderstanding | None = None


def plan_from_understanding(
    understanding: QueryUnderstanding,
    *,
    retrieval_mode: str = "auto",
) -> PlannerResult:
    mode = understanding.retrieval_mode
    if retrieval_mode == "simple":
        mode = "SIMPLE"
    elif retrieval_mode == "multi_constraint":
        mode = "MULTI_CONSTRAINT"

    constraints = [
        Constraint(c.type, c.canonical, list(c.surfaces))
        for c in understanding.constraints
    ]
    return PlannerResult(
        mode=mode,
        constraints=constraints,
        intent=understanding.intent,
        confidence=understanding.confidence,
        used_slm=understanding.used_llm,
        understanding=understanding,
    )


def plan_query(
    query: str,
    *,
    retrieval_mode: str = "auto",
    understanding: QueryUnderstanding | None = None,
) -> PlannerResult:
    u = understanding or understand_query(query, retrieval_mode=retrieval_mode)
    return plan_from_understanding(u, retrieval_mode=retrieval_mode)
