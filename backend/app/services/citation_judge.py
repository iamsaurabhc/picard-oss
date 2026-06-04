from __future__ import annotations

import json
import logging
import re

from app.config import settings
from app.services.citations import CitationMap, MARKER_RE
from app.services.model_router import ModelRole, completion
from app.services.prompt_registry import get_prompt

logger = logging.getLogger(__name__)

JUDGE_PROMPT = """Review whether each cited claim in the answer is supported by its cited source excerpt.
Return JSON only:
{{"valid": true|false, "issues": [{{"marker": N, "issue": "..."}}]}}

Answer:
{answer}

Sources:
{sources}"""


def judge_citations(
    answer: str,
    citation_map: CitationMap,
    *,
    intent: str = "general",
    fail_closed: bool | None = None,
) -> dict:
    """Optional post-synthesis SLM check: claim ↔ cited chunk alignment."""
    if not settings.enable_citation_judge:
        return {"enabled": False, "valid": True, "issues": []}

    use_fail_closed = (
        fail_closed
        if fail_closed is not None
        else settings.citation_judge_fail_closed
    )
    high_risk = intent in {"factual_lookup", "general"}

    if not citation_map.refs:
        return {"enabled": True, "valid": True, "issues": []}

    cited_markers = {int(m.group(1)) for m in MARKER_RE.finditer(answer)}
    if not cited_markers:
        return {"enabled": True, "valid": True, "issues": []}

    source_lines = []
    for ref in citation_map.refs:
        if ref.index in cited_markers:
            source_lines.append(f"[{ref.index}] {ref.preview[:500]}")

    raw = completion(
        messages=[
            {
                "role": "user",
                "content": get_prompt("citation_judge").format(
                    answer=answer,
                    sources="\n".join(source_lines),
                ),
            }
        ],
        role=ModelRole.SLM,
        temperature=0.0,
    )
    if not raw:
        if use_fail_closed and high_risk:
            return {"enabled": True, "valid": False, "issues": [], "skipped": "llm_unavailable"}
        return {"enabled": True, "valid": True, "issues": [], "skipped": "llm_unavailable"}

    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end])
        valid = bool(data.get("valid", True))
        if not valid and use_fail_closed and high_risk:
            valid = False
        return {
            "enabled": True,
            "valid": valid,
            "issues": data.get("issues", []),
        }
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("citation judge parse failed: %s", exc)
        if use_fail_closed and high_risk:
            return {"enabled": True, "valid": False, "issues": [], "skipped": "parse_error"}
        return {"enabled": True, "valid": True, "issues": [], "skipped": "parse_error"}
