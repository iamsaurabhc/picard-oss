"""Shared helpers for PII proxy tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMCallRecorder:
    messages_sent: list[list[dict[str, str]]] = field(default_factory=list)
    completion_response: str = '{"intent":"general","retrieval_mode":"SIMPLE","search_passes":[{"fts_terms":["liability"],"operator":"OR"}],"confidence":0.9}'
    stream_chunks: list[str] = field(default_factory=lambda: ["Answer about ", "<PERSON_1>", "."])

    def install(self, monkeypatch) -> None:
        import app.services.model_router as mr

        from types import SimpleNamespace

        def fake_completion(**kwargs: Any):
            messages = kwargs.get("messages") or []
            self.messages_sent.append([dict(m) for m in messages])
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=self.completion_response))]
            )

        class _Delta:
            def __init__(self, content: str | None) -> None:
                self.content = content

        class _Choice:
            def __init__(self, content: str | None) -> None:
                self.delta = _Delta(content)

        class _Chunk:
            def __init__(self, content: str | None) -> None:
                self.choices = [_Choice(content)]

        class _FakeStream:
            def __init__(self, chunks: list[str]) -> None:
                self._chunks = chunks

            def __aiter__(self):
                self._iter = iter(self._chunks)
                return self

            async def __anext__(self):
                try:
                    return _Chunk(next(self._iter))
                except StopIteration:
                    raise StopAsyncIteration from None

        async def fake_acompletion(**kwargs: Any):
            messages = kwargs.get("messages") or []
            self.messages_sent.append([dict(m) for m in messages])
            return _FakeStream(self.stream_chunks)

        monkeypatch.setattr(mr, "llm_available", lambda: True)
        monkeypatch.setattr("litellm.completion", fake_completion)
        monkeypatch.setattr("litellm.acompletion", fake_acompletion)

    def all_message_text(self) -> str:
        parts: list[str] = []
        for batch in self.messages_sent:
            for msg in batch:
                parts.append(msg.get("content", ""))
        return "\n".join(parts)

    def contains_raw(self, *values: str) -> bool:
        blob = self.all_message_text()
        return any(v in blob for v in values)
