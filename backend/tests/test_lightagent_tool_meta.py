from app.tools.lightagent_meta import normalize_lightagent_tool
from app.tools.registry import tools_for_profile
from app.tools.context import ToolContext
from unittest.mock import MagicMock


def test_normalize_maps_name_to_tool_name():
    def sample(query: str) -> str:
        return query

    sample.tool_info = {"name": "search_corpus", "description": "Search docs"}
    normalize_lightagent_tool(sample)
    assert sample.tool_info["tool_name"] == "search_corpus"
    assert sample.tool_info["tool_params"][0]["name"] == "query"


def test_tools_for_profile_registers_with_lightagent():
    from LightAgent.tools import ToolRegistry

    ctx = ToolContext(db=MagicMock(), workspace_id="ws", session_id="s", profile="firm")
    reg = ToolRegistry()
    for tool in tools_for_profile("firm", ctx):
        assert reg.register_tool(tool)
    assert len(reg.get_tools()) >= 5
