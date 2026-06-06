from __future__ import annotations

import os
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.paths import resolve_picard_data_dir
from app.services.secrets_store import load_secrets
from app.services.settings_store import merged_settings_dict


def _default_data_dir() -> Path:
    return resolve_picard_data_dir()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    picard_data_dir: Path = Field(default_factory=_default_data_dir)
    database_url: str = ""
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:13130",
        "http://127.0.0.1:13130",
        "tauri://localhost",
    ]

    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    slm_model: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    enable_tiered_models: bool = False
    enable_llm_query_understanding: bool = Field(
        default=True,
        validation_alias=AliasChoices("ENABLE_LLM_QUERY_UNDERSTANDING", "ENABLE_QUERY_EXPANSION"),
    )
    enable_query_expansion: bool = Field(
        default=True,
        validation_alias="ENABLE_QUERY_EXPANSION",
    )
    query_expansion_max_phrases: int = 5
    query_expansion_cache_ttl_sec: int = 300
    enable_focus_excerpts: bool = Field(
        default=True,
        validation_alias="ENABLE_FOCUS_EXCERPTS",
    )
    enable_context_ranker: bool = True
    enable_excerpt_selector: bool = True
    query_planner_repair_on_zero_hits: bool = True
    enable_citation_judge: bool = False
    citation_judge_fail_closed: bool = Field(
        default=True,
        validation_alias="CITATION_JUDGE_FAIL_CLOSED",
    )
    prompt_variant: str = Field(default="help_v2", validation_alias="PROMPT_VARIANT")
    enable_hybrid_search: bool = Field(
        default=False,
        validation_alias="ENABLE_HYBRID_SEARCH",
    )
    hybrid_pool_k: int = 16
    hybrid_rrf_k: int = 60
    hybrid_rrf_weight_fts: float = Field(
        default=0.6,
        validation_alias="HYBRID_RRF_WEIGHT_FTS",
    )
    embedding_model_id: str = Field(
        default="BAAI/bge-small-en-v1.5",
        validation_alias="EMBEDDING_MODEL_ID",
    )
    embedding_dims: int = 384
    embedding_cache_dir: str | None = Field(
        default=None,
        validation_alias="EMBEDDING_CACHE_DIR",
    )
    embedding_allow_hub_download: bool = Field(
        default=True,
        validation_alias="EMBEDDING_ALLOW_HUB_DOWNLOAD",
    )
    enable_carp: bool = True
    enable_metadata_llm: bool = False
    enable_regex_nlp: bool = False
    enable_slm_entity_extract: bool = True
    enable_rule_entity_extract: bool = False
    slm_entity_max_pages: int = 5
    planner_rule_confidence: float = 0.9
    carp_max_proximity_tier: str = "SAME_SECTION"
    carp_allow_partial_disclosure: bool = False
    llm_timeout_seconds: float = 30.0

    fts_min_score: float = -25.0
    fts_max_chunks_per_doc: int = 4
    chat_retrieval_pool_k: int = 24
    chat_top_k: int = 12
    chat_max_chunks_per_doc: int = 6
    chat_overview_pool_k: int = 40
    chat_overview_top_k: int = 20
    chat_overview_max_chunks_per_page: int = 2
    overview_page_context_max_docs: int = 3
    overview_max_pages_per_doc: int = 8
    overview_party_scoped_max_pages: int = 12
    overview_excerpt_chars: int = 2500
    chat_listing_pool_k: int = 48
    chat_listing_top_k: int = 24
    chat_listing_min_chunks_per_doc: int = 2
    chat_listing_chunks_per_doc: int = 4
    chat_listing_max_docs: int = 12
    enable_listing_map_reduce: bool = True
    chat_listing_map_chunks_per_doc: int = 4
    chat_listing_map_max_docs: int = 12
    chat_listing_map_excerpt_chars: int = 1200
    chat_listing_discovery_always_fts: bool = True
    chat_listing_discovery_doc_limit: int = 64
    agent_listing_discovery_doc_limit: int = 96
    agent_listing_map_chunks_per_doc: int = 6
    agent_listing_map_max_docs: int = 16
    agent_listing_map_excerpt_chars: int = 1600
    agent_listing_top_k: int = 32
    firm_agent_listing_discovery_doc_limit: int = 96
    firm_agent_listing_map_max_docs: int = 16
    court_agent_listing_discovery_doc_limit: int = 48
    court_agent_listing_map_max_docs: int = 10
    listing_map_reduce_min_docs: int = 4
    listing_max_pages_per_doc: int = 6
    agent_listing_max_pages_per_doc: int = 8
    listing_max_chars_per_page: int = 8000
    listing_large_doc_page_threshold: int = 50
    listing_disable_focus_excerpts: bool = True
    listing_cross_page_refs_max: int = 2
    carp_top_k_bundles: int = 8

    enable_context_expansion: bool = True
    context_expansion_max_chunks: int = 24
    context_expansion_include_page_siblings: bool = True
    context_gap_fill_max_passes: int = 2

    enable_chat: bool = True
    enable_ner_entity_extract: bool = False
    extractor_version: str = "hybrid_v1"
    ner_model_name: str = "gliner_small-v2.1"
    ner_hub_model_id: str = "urchade/gliner_small-v2.1"
    ner_use_onnx: bool = False
    ner_allow_hub_download: bool = True
    ner_threshold_high: float = 0.85
    ner_threshold_low: float = 0.65
    ner_batch_size: int = 8
    entity_ner_max_pages: int = 0

    liteparse_ocr_server_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LITEPARSE_OCR_SERVER_URL", "PADDLE_OCR_SERVER_URL"),
    )
    liteparse_ocr_language: str = Field(
        default="eng",
        validation_alias=AliasChoices("LITEPARSE_OCR_LANGUAGE", "OCR_LANGUAGE"),
    )
    liteparse_dpi_digital: float = Field(default=150.0, validation_alias="LITEPARSE_DPI_DIGITAL")
    liteparse_dpi_ocr: float = Field(default=300.0, validation_alias="LITEPARSE_DPI_OCR")
    liteparse_min_chars_per_page: int = Field(default=25, validation_alias="LITEPARSE_MIN_CHARS_PER_PAGE")
    liteparse_require_paddleocr: bool = Field(default=False, validation_alias="LITEPARSE_REQUIRE_PADDLEOCR")

    update_channel: str = "stable"
    onboarding_complete: bool = False
    show_prompts_in_chat: bool = False
    agent_profile: str = "firm"
    enable_agent_mode: bool = Field(
        default=True,
        validation_alias=AliasChoices("ENABLE_AGENT_MODE", "enable_agent_mode"),
    )
    chat_mode_default: str = Field(
        default="rag",
        validation_alias=AliasChoices("CHAT_MODE_DEFAULT", "chat_mode_default"),
    )
    agent_max_iterations: int = Field(
        default=5,
        validation_alias=AliasChoices("AGENT_MAX_ITERATIONS", "agent_max_iterations"),
    )
    agent_scope_confirm_min_docs: int = Field(
        default=10,
        validation_alias=AliasChoices(
            "AGENT_SCOPE_CONFIRM_MIN_DOCS",
            "agent_scope_confirm_min_docs",
        ),
    )
    agent_skip_scope_hitl: bool = Field(
        default=False,
        validation_alias=AliasChoices("AGENT_SKIP_SCOPE_HITL", "agent_skip_scope_hitl"),
    )
    mem0_data_dir: str | None = Field(
        default=None,
        validation_alias=AliasChoices("MEM0_DATA_DIR", "mem0_data_dir"),
    )
    mem0_store_on_run_end: bool = Field(
        default=True,
        validation_alias=AliasChoices("MEM0_STORE_ON_RUN_END", "mem0_store_on_run_end"),
    )
    mem0_max_entries: int = Field(
        default=0,
        validation_alias=AliasChoices("MEM0_MAX_ENTRIES", "mem0_max_entries"),
    )
    release_manifest_url: str = Field(
        default="https://raw.githubusercontent.com/iamsaurabhc/picard-oss/gh-pages/releases/manifest.json",
        validation_alias="PICARD_RELEASE_MANIFEST_URL",
    )

    @property
    def db_path(self) -> Path:
        url = self.database_url
        if url.startswith("sqlite:///"):
            raw = url.removeprefix("sqlite:///")
            path = Path(raw)
            if not path.is_absolute():
                return Path.cwd() / path
            return path
        raise ValueError("Only sqlite:/// URLs are supported")

    @property
    def pdfs_dir(self) -> Path:
        return self.picard_data_dir / "pdfs"

    @property
    def mem0_dir(self) -> Path:
        if self.mem0_data_dir:
            return Path(self.mem0_data_dir)
        return self.picard_data_dir / "mem0"

    @property
    def embedding_model_cache_path(self) -> Path:
        if self.embedding_cache_dir:
            return Path(self.embedding_cache_dir)
        return self.picard_data_dir / "models" / "fastembed"


def _build_settings() -> Settings:
    data_dir = resolve_picard_data_dir()
    os.environ.setdefault("PICARD_DATA_DIR", str(data_dir))
    merged = merged_settings_dict(data_dir)
    if not merged.get("database_url"):
        merged["database_url"] = f"sqlite:///{data_dir / 'picard.db'}"
    if isinstance(merged.get("picard_data_dir"), str):
        merged["picard_data_dir"] = Path(merged["picard_data_dir"])
    # Env vars still override via pydantic when we construct Settings()
    s = Settings(**{k: v for k, v in merged.items() if k in Settings.model_fields})
    secrets = load_secrets(data_dir)
    if secrets.get("openai_api_key"):
        s.openai_api_key = secrets["openai_api_key"]
    if secrets.get("anthropic_api_key"):
        s.anthropic_api_key = secrets["anthropic_api_key"]
    # .env keys override secrets if explicitly set in dev
    env_openai = os.environ.get("OPENAI_API_KEY")
    if env_openai:
        s.openai_api_key = env_openai or None
    env_anthropic = os.environ.get("ANTHROPIC_API_KEY")
    if env_anthropic:
        s.anthropic_api_key = env_anthropic or None
    return s


def _sync_settings_in_place(target: Settings, fresh: Settings) -> None:
    """Update the shared Settings instance so all `from app.config import settings` bindings stay current."""
    for field_name in Settings.model_fields:
        setattr(target, field_name, getattr(fresh, field_name))


def reload_settings() -> Settings:
    global settings
    fresh = _build_settings()
    _sync_settings_in_place(settings, fresh)
    return settings


settings = _build_settings()
