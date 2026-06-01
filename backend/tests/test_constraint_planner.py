from app.services.constraint_planner import Constraint, plan_from_understanding, plan_query
from app.services.query_understanding import QueryConstraint, QueryUnderstanding


def test_planner_simple_query():
    result = plan_query("What is the liability cap?", retrieval_mode="auto")
    assert result.mode == "SIMPLE"


def test_planner_multi_constraint_rules():
    result = plan_query(
        "case context for party ABC, date 18/05/2019, with condition C",
        retrieval_mode="auto",
    )
    assert len(result.constraints) >= 2
    types = {c.type for c in result.constraints}
    assert "date" in types or "condition" in types or "party" in types


def test_planner_force_simple():
    u = QueryUnderstanding(
        retrieval_mode="MULTI_CONSTRAINT",
        constraints=[
            QueryConstraint(type="party", canonical="abc", surfaces=["ABC"]),
            QueryConstraint(type="date", canonical="2019-05-18", surfaces=["18/05/2019"]),
        ],
        intent="case_context",
    )
    result = plan_from_understanding(u, retrieval_mode="simple")
    assert result.mode == "SIMPLE"


def test_planner_from_understanding():
    u = QueryUnderstanding(
        retrieval_mode="MULTI_CONSTRAINT",
        constraints=[
            QueryConstraint(type="party", canonical="supreme court"),
            QueryConstraint(type="amount", canonical="1000_gbp"),
        ],
        intent="case_context",
    )
    result = plan_from_understanding(u, retrieval_mode="multi_constraint")
    assert result.mode == "MULTI_CONSTRAINT"
    assert len(result.constraints) == 2
