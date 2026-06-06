from __future__ import annotations

from typing import Any

from app.tools.context import ToolContext
from app.tools.lightagent_meta import normalize_lightagent_tool

COURT_DENYLIST = frozenset(
    {
        "risk_score_documents",
        "predict_case_outcome",
        "credibility_score_witness",
        "surveillance_monitor",
    }
)


def tools_for_profile(profile: str, ctx: ToolContext) -> list[Any]:
    from app.tools.corpus import bind_corpus_tools
    from app.tools.tabular import bind_tabular_tools
    from app.tools.vault import bind_vault_tools
    from app.tools.workflow_author import bind_workflow_tools

    tools: list[Any] = []
    tools.extend(bind_vault_tools(ctx))
    tools.extend(bind_corpus_tools(ctx))
    tools.extend(bind_tabular_tools(ctx))
    tools.extend(bind_workflow_tools(ctx))
    tools = [normalize_lightagent_tool(t) for t in tools]
    if profile == "court":
        tools = [
            t
            for t in tools
            if getattr(t, "tool_info", {}).get("tool_name") not in COURT_DENYLIST
        ]
    return tools
