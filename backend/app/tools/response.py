from __future__ import annotations

import json
from typing import Any


def tool_json(
    *,
    refused: bool = False,
    content: str = "",
    references: list[dict] | None = None,
    tier: str = "A",
    error: str | None = None,
    **extra: Any,
) -> str:
    payload: dict[str, Any] = {
        "refused": refused,
        "content": content,
        "references": references or [],
        "tier": tier,
        "citation_map_version": "1",
    }
    if error:
        payload["error"] = error
    payload.update(extra)
    return json.dumps(payload)
