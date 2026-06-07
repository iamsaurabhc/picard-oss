import asyncio

import pytest

from app.config import settings
from app.services.model_router import completion, stream_completion
from app.services.pii_proxy import get_active_proxy, pii_request_scope


def test_ollama_bypasses_pii(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")

    sent: list[list[dict]] = []

    from types import SimpleNamespace

    def fake_completion(**kwargs):
        sent.append(kwargs["messages"])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Rahul Mehta"))]
        )

    monkeypatch.setattr("litellm.completion", fake_completion)

    with pii_request_scope(enabled=True):
        out = completion(messages=[{"role": "user", "content": "Rahul Mehta"}])
    assert out == "Rahul Mehta"
    assert "Rahul Mehta" in sent[0][0]["content"]


def test_cloud_masks_and_restores_completion(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "pii_use_presidio", False)

    sent: list[list[dict]] = []

    from types import SimpleNamespace

    def fake_completion(**kwargs):
        sent.append(kwargs["messages"])
        content = kwargs["messages"][0]["content"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    monkeypatch.setattr("litellm.completion", fake_completion)

    with pii_request_scope(enabled=True):
        proxy = get_active_proxy()
        assert proxy is not None
        proxy.register_text("rahul@acme.in")
        out = completion(messages=[{"role": "user", "content": "Email rahul@acme.in"}])
    assert out is not None
    assert "rahul@acme.in" in out
    blob = sent[0][0]["content"]
    assert "rahul@acme.in" not in blob


def test_cloud_stream_restore(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "pii_use_presidio", False)

    from types import SimpleNamespace

    class _Stream:
        def __init__(self, chunks):
            self._chunks = iter(chunks)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                content = next(self._chunks)
                return SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
                )
            except StopIteration:
                raise StopAsyncIteration from None

    async def fake_acompletion(**kwargs):
        return _Stream(["<EMAIL", "_ADDRESS_1> ok"])

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)

    async def _run():
        parts = []
        with pii_request_scope(enabled=True):
            proxy = get_active_proxy()
            assert proxy is not None
            proxy.register_text("rahul@acme.in")
            token = proxy.reverse_map["rahul@acme.in"]
            async for delta in stream_completion(messages=[{"role": "user", "content": "hi"}]):
                parts.append(delta)
            assert token.startswith("<")
        return parts

    parts = asyncio.run(_run())
    assert "".join(parts) == "rahul@acme.in ok"
