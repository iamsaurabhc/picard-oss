"""Pipeline prompt defaults and user overrides."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.paths import config_dir, resolve_picard_data_dir

logger = logging.getLogger(__name__)

PROMPT_KEYS = frozenset(
    {
        "query_understanding",
        "context_ranker",
        "coverage_ranker",
        "excerpt_selector",
        "citation_judge",
    }
)

_DEFAULTS_CACHE: dict[str, str] | None = None


def _load_defaults() -> dict[str, str]:
    global _DEFAULTS_CACHE
    if _DEFAULTS_CACHE is not None:
        return _DEFAULTS_CACHE
    from app.services.citation_judge import JUDGE_PROMPT
    from app.services.context_ranker import COVERAGE_RANKER_PROMPT, RANKER_PROMPT
    from app.services.excerpt_selector import EXCERPT_SELECTOR_PROMPT
    from app.services.query_understanding import QUERY_PLANNER_PROMPT

    _DEFAULTS_CACHE = {
        "query_understanding": QUERY_PLANNER_PROMPT,
        "context_ranker": RANKER_PROMPT,
        "coverage_ranker": COVERAGE_RANKER_PROMPT,
        "excerpt_selector": EXCERPT_SELECTOR_PROMPT,
        "citation_judge": JUDGE_PROMPT,
    }
    return _DEFAULTS_CACHE


def overrides_path(data_dir: Path | None = None) -> Path:
    return config_dir(data_dir or resolve_picard_data_dir()) / "prompt_overrides.json"


def _load_overrides(data_dir: Path | None = None) -> dict[str, str]:
    path = overrides_path(data_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {k: str(v) for k, v in data.items() if k in PROMPT_KEYS}
    except json.JSONDecodeError:
        return {}


def get_prompt(key: str, data_dir: Path | None = None) -> str:
    if key not in PROMPT_KEYS:
        raise KeyError(f"Unknown prompt key: {key}")
    defaults = _load_defaults()
    overrides = _load_overrides(data_dir)
    return overrides.get(key, defaults[key])


def list_prompts(data_dir: Path | None = None) -> list[dict[str, Any]]:
    overrides = _load_overrides(data_dir)
    defaults = _load_defaults()
    out = []
    for key, default in defaults.items():
        current = overrides.get(key, default)
        out.append(
            {
                "key": key,
                "is_overridden": key in overrides,
                "preview": current[:200] + ("…" if len(current) > 200 else ""),
                "length": len(current),
            }
        )
    return out


def get_prompt_full(key: str, data_dir: Path | None = None) -> dict[str, Any]:
    text = get_prompt(key, data_dir)
    defaults = _load_defaults()
    return {
        "key": key,
        "text": text,
        "is_overridden": key in _load_overrides(data_dir),
        "default_preview": defaults[key][:200],
    }


def save_prompt_override(key: str, text: str, data_dir: Path | None = None) -> None:
    if key not in PROMPT_KEYS:
        raise KeyError(f"Unknown prompt key: {key}")
    data = data_dir or resolve_picard_data_dir()
    config_dir(data).mkdir(parents=True, exist_ok=True)
    overrides = _load_overrides(data)
    overrides[key] = text
    overrides_path(data).write_text(json.dumps(overrides, indent=2), encoding="utf-8")


def reset_prompt(key: str, data_dir: Path | None = None) -> None:
    overrides = _load_overrides(data_dir)
    overrides.pop(key, None)
    path = overrides_path(data_dir)
    if overrides:
        path.write_text(json.dumps(overrides, indent=2), encoding="utf-8")
    elif path.is_file():
        path.unlink()
