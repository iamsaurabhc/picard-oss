from unittest.mock import patch

from app.services.model_router import ModelRole, llm_available, resolve_model
from app.config import settings


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


def test_llm_available_openai_without_key(monkeypatch):
    settings.llm_provider = "openai"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert llm_available() is False


def test_llm_available_ollama():
    settings.llm_provider = "ollama"
    assert llm_available() is True
