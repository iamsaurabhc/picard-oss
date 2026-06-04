from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import Settings, reload_settings, settings
from app.services.components import install_component, list_components
from app.services.model_router import llm_available
from app.services.secrets_store import save_secrets, secrets_status
from app.services.settings_store import (
    USER_SETTING_KEYS,
    load_user_settings,
    reset_user_settings,
    save_user_settings,
)
from app.version import build_metadata, read_version

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsOut(BaseModel):
    llm_provider: str
    llm_model: str
    ollama_base_url: str
    enable_tiered_models: bool
    slm_model: str | None
    enable_llm_query_understanding: bool
    enable_query_expansion: bool
    enable_context_ranker: bool
    enable_excerpt_selector: bool
    enable_carp: bool
    enable_ner_entity_extract: bool
    enable_slm_entity_extract: bool
    liteparse_ocr_server_url: str | None
    picard_data_dir: str
    onboarding_complete: bool
    show_prompts_in_chat: bool
    update_channel: str
    release_manifest_url: str
    llm_configured: bool
    openai_api_key_set: bool
    anthropic_api_key_set: bool
    version: str


class SettingsUpdate(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None
    ollama_base_url: str | None = None
    enable_tiered_models: bool | None = None
    slm_model: str | None = None
    enable_llm_query_understanding: bool | None = None
    enable_query_expansion: bool | None = None
    enable_context_ranker: bool | None = None
    enable_excerpt_selector: bool | None = None
    enable_carp: bool | None = None
    enable_ner_entity_extract: bool | None = None
    enable_slm_entity_extract: bool | None = None
    liteparse_ocr_server_url: str | None = None
    onboarding_complete: bool | None = None
    show_prompts_in_chat: bool | None = None
    update_channel: str | None = None
    release_manifest_url: str | None = None


class SecretsUpdate(BaseModel):
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None


class ResetRequest(BaseModel):
    keep_secrets: bool = True


def _settings_to_out(s: Settings) -> SettingsOut:
    status = secrets_status(s.picard_data_dir)
    return SettingsOut(
        llm_provider=s.llm_provider,
        llm_model=s.llm_model,
        ollama_base_url=s.ollama_base_url,
        enable_tiered_models=s.enable_tiered_models,
        slm_model=s.slm_model,
        enable_llm_query_understanding=s.enable_llm_query_understanding,
        enable_query_expansion=s.enable_query_expansion,
        enable_context_ranker=s.enable_context_ranker,
        enable_excerpt_selector=s.enable_excerpt_selector,
        enable_carp=s.enable_carp,
        enable_ner_entity_extract=s.enable_ner_entity_extract,
        enable_slm_entity_extract=s.enable_slm_entity_extract,
        liteparse_ocr_server_url=s.liteparse_ocr_server_url,
        picard_data_dir=str(s.picard_data_dir),
        onboarding_complete=s.onboarding_complete,
        show_prompts_in_chat=s.show_prompts_in_chat,
        update_channel=s.update_channel,
        release_manifest_url=s.release_manifest_url,
        llm_configured=llm_available(),
        openai_api_key_set=status.get("openai_api_key_set", False),
        anthropic_api_key_set=status.get("anthropic_api_key_set", False),
        version=read_version(),
    )


@router.get("", response_model=SettingsOut)
def get_settings():
    return _settings_to_out(settings)


@router.put("", response_model=SettingsOut)
def update_settings(body: SettingsUpdate):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return _settings_to_out(settings)
    save_user_settings(updates, settings.picard_data_dir)
    s = reload_settings()
    return _settings_to_out(s)


@router.put("/secrets")
def update_secrets(body: SecretsUpdate):
    save_secrets(body.model_dump(exclude_none=True), settings.picard_data_dir)
    reload_settings()
    return {"ok": True, **secrets_status(settings.picard_data_dir)}


@router.post("/reset", response_model=SettingsOut)
def reset_settings(body: ResetRequest):
    reset_user_settings(keep_secrets=body.keep_secrets, data_dir=settings.picard_data_dir)
    s = reload_settings()
    return _settings_to_out(s)


@router.get("/components")
def get_components():
    return {"components": list_components()}


@router.post("/components/{component_id}/install")
def install_component_pack(component_id: str):
    result = install_component(component_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message", "install failed"))
    return result


@router.get("/onboarding-status")
def onboarding_status():
    user = load_user_settings(settings.picard_data_dir)
    return {
        "needs_onboarding": not user.get("onboarding_complete", False),
        "llm_configured": llm_available(),
    }
