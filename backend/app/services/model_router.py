from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


class ModelRole(str, Enum):
    SLM = "slm"
    LLM = "llm"


def resolve_model(role: ModelRole = ModelRole.LLM) -> str:
    if settings.enable_tiered_models and role == ModelRole.SLM and settings.slm_model:
        return settings.slm_model
    model = settings.llm_model
    if settings.llm_provider == "ollama" and not model.startswith("ollama/"):
        return f"ollama/{model}"
    return model


def should_use_slm(step: str) -> bool:
    if not settings.enable_tiered_models:
        return False
    return step in {
        "constraint_planner",
        "query_expansion",
        "query_understanding",
        "context_ranker",
        "citation_judge",
        "metadata_extractor",
        "excerpt_selector",
        "query_planner_repair",
    }


def _openai_key() -> str | None:
    return settings.openai_api_key


def _anthropic_key() -> str | None:
    return settings.anthropic_api_key


def llm_available() -> bool:
    if settings.llm_provider == "ollama":
        return True
    if settings.llm_provider == "openai":
        return bool(_openai_key())
    if settings.llm_provider == "anthropic":
        return bool(_anthropic_key())
    return True


def _litellm_api_key() -> str | None:
    if settings.llm_provider == "openai":
        return _openai_key()
    if settings.llm_provider == "anthropic":
        return _anthropic_key()
    return None


def completion(
    *,
    messages: list[dict[str, str]],
    role: ModelRole = ModelRole.LLM,
    temperature: float = 0.0,
    response_format: dict[str, Any] | None = None,
) -> str | None:
    key = _litellm_api_key()
    if not llm_available():
        logger.warning("LLM unavailable; skipping completion")
        return None
    try:
        import litellm

        if settings.llm_provider == "ollama":
            litellm.api_base = settings.ollama_base_url

        kwargs: dict[str, Any] = {
            "model": resolve_model(role),
            "messages": messages,
            "temperature": temperature,
            "timeout": settings.llm_timeout_seconds,
        }
        if key:
            kwargs["api_key"] = key
        if response_format:
            kwargs["response_format"] = response_format
        response = litellm.completion(**kwargs)
        content = response.choices[0].message.content
        return content.strip() if content else None
    except Exception as exc:
        logger.warning("litellm completion failed: %s", exc)
        return None


async def stream_completion(
    *,
    messages: list[dict[str, str]],
    role: ModelRole = ModelRole.LLM,
    temperature: float = 0.0,
):
    """Yield text deltas from litellm streaming completion."""
    key = _litellm_api_key()
    if not llm_available():
        yield "LLM is not configured. Set LLM_PROVIDER and credentials."
        return
    try:
        import litellm

        if settings.llm_provider == "ollama":
            litellm.api_base = settings.ollama_base_url

        kwargs: dict[str, Any] = {
            "model": resolve_model(role),
            "messages": messages,
            "temperature": temperature,
            "timeout": settings.llm_timeout_seconds,
            "stream": True,
        }
        if key:
            kwargs["api_key"] = key
        response = await litellm.acompletion(**kwargs)
        async for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    except Exception as exc:
        logger.warning("litellm stream failed: %s", exc)
        yield f"[Error: {exc}]"
