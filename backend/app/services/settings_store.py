"""Load/save user settings merged with shipped defaults."""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.paths import bundled_defaults_path, config_dir, resolve_picard_data_dir

logger = logging.getLogger(__name__)


def merge_cors_origins(
    user_origins: list[str] | None,
    default_origins: list[str] | None,
) -> list[str]:
    """Always include shipped desktop/webview origins; user list may omit new ports after upgrades."""
    combined = list(user_origins or []) + list(default_origins or [])
    return list(dict.fromkeys(combined))


# Fields persisted in user settings.json (non-secret)
USER_SETTING_KEYS = frozenset(
    {
        "llm_provider",
        "llm_model",
        "ollama_base_url",
        "enable_tiered_models",
        "slm_model",
        "enable_llm_query_understanding",
        "enable_query_expansion",
        "query_expansion_max_phrases",
        "query_expansion_cache_ttl_sec",
        "enable_focus_excerpts",
        "enable_context_ranker",
        "enable_excerpt_selector",
        "query_planner_repair_on_zero_hits",
        "enable_citation_judge",
        "citation_judge_fail_closed",
        "prompt_variant",
        "enable_hybrid_search",
        "embedding_model_id",
        "embedding_dims",
        "embedding_cache_dir",
        "embedding_allow_hub_download",
        "hybrid_pool_k",
        "hybrid_rrf_k",
        "hybrid_rrf_weight_fts",
        "enable_carp",
        "enable_metadata_llm",
        "enable_regex_nlp",
        "enable_slm_entity_extract",
        "enable_rule_entity_extract",
        "slm_entity_max_pages",
        "enable_ner_entity_extract",
        "planner_rule_confidence",
        "carp_max_proximity_tier",
        "carp_allow_partial_disclosure",
        "enable_context_expansion",
        "context_expansion_max_chunks",
        "context_expansion_include_page_siblings",
        "context_gap_fill_max_passes",
        "chat_retrieval_pool_k",
        "chat_top_k",
        "chat_overview_pool_k",
        "chat_overview_top_k",
        "chat_overview_max_chunks_per_page",
        "liteparse_ocr_server_url",
        "liteparse_ocr_language",
        "liteparse_dpi_digital",
        "liteparse_dpi_ocr",
        "liteparse_min_chars_per_page",
        "liteparse_require_paddleocr",
        "picard_data_dir",
        "cors_origins",
        "update_channel",
        "onboarding_complete",
        "show_prompts_in_chat",
        "agent_profile",
        "enable_agent_mode",
        "chat_mode_default",
        "agent_max_iterations",
        "agent_scope_confirm_min_docs",
        "agent_skip_scope_hitl",
        "mem0_store_on_run_end",
        "mem0_max_entries",
    }
)


def load_shipped_defaults() -> dict[str, Any]:
    path = bundled_defaults_path()
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def user_settings_path(data_dir: Path | None = None) -> Path:
    return config_dir(data_dir) / "settings.json"


def ensure_user_settings_file(data_dir: Path | None = None) -> Path:
    data = data_dir or resolve_picard_data_dir()
    cfg = config_dir(data)
    cfg.mkdir(parents=True, exist_ok=True)
    path = user_settings_path(data)
    defaults = load_shipped_defaults()
    if not path.is_file():
        to_write = {k: v for k, v in defaults.items() if k in USER_SETTING_KEYS or k == "onboarding_complete"}
        path.write_text(json.dumps(to_write, indent=2), encoding="utf-8")
    else:
        _migrate_cors_origins(path, defaults)
    return path


def _migrate_cors_origins(path: Path, defaults: dict[str, Any]) -> None:
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    merged = merge_cors_origins(current.get("cors_origins"), defaults.get("cors_origins"))
    if merged == current.get("cors_origins"):
        return
    current["cors_origins"] = merged
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")


def load_user_settings(data_dir: Path | None = None) -> dict[str, Any]:
    path = user_settings_path(data_dir or resolve_picard_data_dir())
    if not path.is_file():
        ensure_user_settings_file(data_dir)
        path = user_settings_path(data_dir or resolve_picard_data_dir())
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Invalid settings.json; using defaults only")
        return {}


def save_user_settings(updates: dict[str, Any], data_dir: Path | None = None) -> dict[str, Any]:
    data = data_dir or resolve_picard_data_dir()
    ensure_user_settings_file(data)
    current = load_user_settings(data)
    filtered = {k: v for k, v in updates.items() if k in USER_SETTING_KEYS}
    current.update(filtered)
    user_settings_path(data).write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def merged_settings_dict(data_dir: Path | None = None) -> dict[str, Any]:
    data = data_dir or resolve_picard_data_dir()
    defaults = load_shipped_defaults()
    user = load_user_settings(data)
    merged = deepcopy(defaults)
    merged.update(user)
    merged["cors_origins"] = merge_cors_origins(user.get("cors_origins"), defaults.get("cors_origins"))
    merged["picard_data_dir"] = str(data)
    merged["database_url"] = f"sqlite:///{data / 'picard.db'}"
    return merged


def reset_user_settings(*, keep_secrets: bool = True, data_dir: Path | None = None) -> dict[str, Any]:
    data = data_dir or resolve_picard_data_dir()
    defaults = load_shipped_defaults()
    to_write = {k: v for k, v in defaults.items() if k in USER_SETTING_KEYS}
    if not keep_secrets:
        to_write["onboarding_complete"] = False
    user_settings_path(data).write_text(json.dumps(to_write, indent=2), encoding="utf-8")
    return to_write
