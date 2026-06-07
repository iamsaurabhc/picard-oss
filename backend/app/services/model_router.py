from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from app.config import settings
from app.services.pii_proxy import get_active_proxy, should_pii_protect

logger = logging.getLogger(__name__)


def _prepare_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    proxy = get_active_proxy()
    if proxy is None or not should_pii_protect():
        return messages
    return proxy.anonymize_messages(messages)


def _restore_text(text: str) -> str:
    proxy = get_active_proxy()
    if proxy is None or not should_pii_protect():
        return text
    return proxy.restore(text)


def _restore_stream_chunk(chunk: str) -> str:
    proxy = get_active_proxy()
    if proxy is None or not should_pii_protect():
        return chunk
    return proxy.restore_stream_chunk(chunk)


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
        kwargs["messages"] = _prepare_messages(messages)
        response = litellm.completion(**kwargs)
        content = response.choices[0].message.content
        if not content:
            return None
        return _restore_text(content.strip())
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
        kwargs["messages"] = _prepare_messages(messages)
        response = await litellm.acompletion(**kwargs)
        async for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                restored = _restore_stream_chunk(delta)
                if restored:
                    yield restored
        proxy = get_active_proxy()
        if proxy is not None and should_pii_protect():
            tail = proxy.flush_stream()
            if tail:
                yield tail
    except Exception as exc:
        logger.warning("litellm stream failed: %s", exc)
        yield f"[Error: {exc}]"
