"""WF-01: workflow_id pins query understanding intent when single allowed_intent."""

from app.services.query_understanding import QueryUnderstanding, FtsPlan
from app.services.workflows_store import apply_workflow_intent_hint


def test_apply_single_intent_hint():
    u = QueryUnderstanding(
        retrieval_mode="SIMPLE",
        intent="general",
        fts=FtsPlan(),
    )
    out = apply_workflow_intent_hint(u, "case_overview", ["case_overview"])
    assert out.intent == "case_overview"


def test_apply_multi_intent_clamps_unknown():
    u = QueryUnderstanding(
        retrieval_mode="SIMPLE",
        intent="general",
        fts=FtsPlan(),
    )
    out = apply_workflow_intent_hint(
        u,
        None,
        ["obligations", "factual_lookup"],
    )
    assert out.intent == "obligations"
