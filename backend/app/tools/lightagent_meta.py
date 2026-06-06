"""Map Picard tool callables to LightAgent tool_info schema."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any


def normalize_lightagent_tool(func: Callable[..., Any]) -> Callable[..., Any]:
    """Ensure func.tool_info uses tool_name / tool_description / tool_params (LightAgent 0.6.x)."""
    info = dict(getattr(func, "tool_info", None) or {})
    if info.get("tool_name"):
        return func

    tool_name = info.get("name") or func.__name__
    tool_description = (info.get("description") or func.__doc__ or tool_name).strip().split("\n")[0]

    tool_params: list[dict[str, Any]] = []
    for pname, param in inspect.signature(func).parameters.items():
        ann = param.annotation
        if ann is inspect.Parameter.empty or ann is str:
            ptype = "string"
        elif ann is int or ann is float:
            ptype = "number"
        elif ann is bool:
            ptype = "boolean"
        else:
            ptype = "string"
        tool_params.append(
            {
                "name": pname,
                "description": pname.replace("_", " "),
                "type": ptype,
                "required": param.default is inspect.Parameter.empty,
            }
        )

    func.tool_info = {
        "tool_name": tool_name,
        "tool_description": tool_description,
        "tool_params": tool_params,
    }
    return func
