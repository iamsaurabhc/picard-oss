from unittest.mock import patch

from app.config import reload_settings, settings
from app.services import model_router
from app.services.model_router import ModelRole, llm_available, resolve_model
from app.services.secrets_store import save_secrets


def test_resolve_model_single_mode():
    settings.enable_tiered_models = False
    settings.llm_model = "gpt-4o-mini"
    assert resolve_model(ModelRole.LLM) == "gpt-4o-mini"
    assert resolve_model(ModelRole.SLM) == "gpt-4o-mini"


def test_resolve_model_tiered():
    settings.enable_tiered_models = True
    settings.llm_model = "gpt-4o"
    settings.slm_model = "gpt-4o-mini"
    assert resolve_model(ModelRole.SLM) == "gpt-4o-mini"
    assert resolve_model(ModelRole.LLM) == "gpt-4o"


def test_resolve_model_ollama_prefix():
    settings.enable_tiered_models = False
    settings.llm_provider = "ollama"
    settings.llm_model = "llama3.2"
    assert resolve_model() == "ollama/llama3.2"


def test_llm_available_openai_without_key(monkeypatch, tmp_path):
    monkeypatch.setenv("PICARD_DATA_DIR", str(tmp_path))
    reload_settings()
    assert llm_available() is False


def test_llm_available_ollama():
    settings.llm_provider = "ollama"
    assert llm_available() is True


def test_reload_settings_propagates_to_model_router(monkeypatch, tmp_path):
    monkeypatch.setenv("PICARD_DATA_DIR", str(tmp_path))
    settings.llm_provider = "openai"
    settings.openai_api_key = None
    save_secrets({"openai_api_key": "sk-test"}, tmp_path)
    assert model_router.settings is settings
    reload_settings()
    assert model_router.settings is settings
    assert settings.openai_api_key == "sk-test"
    assert llm_available() is True
