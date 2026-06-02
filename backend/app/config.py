from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    picard_data_dir: Path = Path(".picard-data")
    database_url: str = "sqlite:///.picard-data/picard.db"
    cors_origins: list[str] = ["http://localhost:3000"]

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
    enable_context_ranker: bool = True
    enable_excerpt_selector: bool = True
    query_planner_repair_on_zero_hits: bool = True
    enable_citation_judge: bool = False
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
    chat_listing_pool_k: int = 48
    chat_listing_top_k: int = 24
    chat_listing_min_chunks_per_doc: int = 2
    chat_listing_chunks_per_doc: int = 4
    chat_listing_max_docs: int = 12
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
        default="http://localhost:8829/ocr",
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


settings = Settings()
