"""Request-scoped PII proxy: detect locally, mask for cloud LLMs, restore responses."""

from __future__ import annotations

import asyncio
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from app.config import settings

logger = logging.getLogger(__name__)

_pii_proxy: ContextVar[PIIProxy | None] = ContextVar("pii_proxy", default=None)
_pii_enabled: ContextVar[bool] = ContextVar("pii_enabled", default=False)

_PII_HYGIENE_LINE = (
    "Placeholder tokens like <PERSON_1> are redacted values — preserve them verbatim; "
    "do not infer or expand real identities."
)

_REGEX_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL_ADDRESS", re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")),
    ("PHONE_NUMBER", re.compile(r"(?:\+91[\-\s]?)?[6-9]\d{9}")),
    ("PAN", re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")),
    ("AADHAAR", re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b")),
]

_executor: ThreadPoolExecutor | None = None
_analyzer_engine: Any = None
_presidio_checked = False
_presidio_available = False


def pii_protection_available() -> bool:
    """True when regex fallback or Presidio analyzer is usable."""
    return True  # regex always available


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pii")
    return _executor


def _presidio_ready() -> bool:
    global _presidio_checked, _presidio_available, _analyzer_engine
    if _presidio_checked:
        return _presidio_available
    _presidio_checked = True
    if not settings.pii_use_presidio:
        return False
    try:
        from presidio_analyzer import AnalyzerEngine

        _analyzer_engine = AnalyzerEngine()
        # Warm spacy model on first use
        _analyzer_engine.analyze(text="warmup", language="en")
        _presidio_available = True
    except Exception as exc:
        logger.info("Presidio unavailable; using regex-only PII: %s", exc)
        _presidio_available = False
    return _presidio_available


def get_active_proxy() -> PIIProxy | None:
    return _pii_proxy.get()


def should_pii_protect() -> bool:
    if settings.llm_provider == "ollama":
        return False
    return bool(_pii_enabled.get() and _pii_proxy.get() is not None)


@contextmanager
def pii_request_scope(*, enabled: bool) -> Iterator[PIIProxy | None]:
    if not enabled or settings.llm_provider == "ollama" or not pii_protection_available():
        token_en = _pii_enabled.set(False)
        token_px = _pii_proxy.set(None)
        try:
            yield None
        finally:
            _pii_enabled.reset(token_en)
            _pii_proxy.reset(token_px)
        return

    proxy = PIIProxy()
    token_en = _pii_enabled.set(True)
    token_px = _pii_proxy.set(proxy)
    try:
        yield proxy
    finally:
        _pii_enabled.reset(token_en)
        _pii_proxy.reset(token_px)


def pii_enabled_for_chat(body: Any) -> bool:
    flag = getattr(body, "enable_pii_protection", settings.enable_pii_protection_default)
    return bool(flag)


def pii_enabled_for_settings_default() -> bool:
    return bool(settings.enable_pii_protection_default)


class StreamingPIIRestorer:
    """Buffers partial placeholder tokens across streamed LLM deltas."""

    def __init__(self, forward_map: dict[str, str]) -> None:
        self._forward = forward_map
        self._buffer = ""

    def feed(self, chunk: str) -> str:
        self._buffer += chunk
        return self._emit_safe()

    def flush(self) -> str:
        rest = self._buffer
        self._buffer = ""
        return self._restore_complete(rest)

    def _emit_safe(self) -> str:
        out: list[str] = []
        while self._buffer:
            lt = self._buffer.find("<")
            if lt < 0:
                out.append(self._restore_complete(self._buffer))
                self._buffer = ""
                break
            if lt > 0:
                out.append(self._restore_complete(self._buffer[:lt]))
                self._buffer = self._buffer[lt:]
            gt = self._buffer.find(">")
            if gt < 0:
                if len(self._buffer) > 64:
                    out.append(self._buffer[0])
                    self._buffer = self._buffer[1:]
                break
            token = self._buffer[: gt + 1]
            self._buffer = self._buffer[gt + 1 :]
            out.append(self._forward.get(token, token))
        return "".join(out)

    def _restore_complete(self, text: str) -> str:
        for token, original in self._forward.items():
            text = text.replace(token, original)
        return text


class PIIProxy:
    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.forward_map: dict[str, str] = {}
        self.reverse_map: dict[str, str] = {}
        self._stream_restorer = StreamingPIIRestorer(self.forward_map)

    def _token(self, entity_type: str, value: str) -> str:
        if value in self.reverse_map:
            return self.reverse_map[value]
        n = self.counters.get(entity_type, 0) + 1
        self.counters[entity_type] = n
        token = f"<{entity_type}_{n}>"
        self.forward_map[token] = value
        self.reverse_map[value] = token
        return token

    def _regex_spans(self, text: str) -> list[tuple[int, int, str, str]]:
        spans: list[tuple[int, int, str, str]] = []
        for entity_type, pattern in _REGEX_PATTERNS:
            for match in pattern.finditer(text):
                spans.append((match.start(), match.end(), entity_type, match.group(0)))
        return spans

    def _presidio_spans(self, text: str) -> list[tuple[int, int, str, str]]:
        if not _presidio_ready() or _analyzer_engine is None:
            return []
        try:
            results = _analyzer_engine.analyze(text=text, language="en")
        except Exception as exc:
            logger.debug("Presidio analyze failed: %s", exc)
            return []
        spans: list[tuple[int, int, str, str]] = []
        for r in results:
            original = text[r.start : r.end]
            if original.strip():
                spans.append((r.start, r.end, r.entity_type, original))
        return spans

    def _collect_spans(self, text: str) -> list[tuple[int, int, str, str]]:
        spans = self._regex_spans(text)
        spans.extend(self._presidio_spans(text))
        if not spans:
            return []
        spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
        merged: list[tuple[int, int, str, str]] = []
        for start, end, etype, val in spans:
            if merged and start < merged[-1][1]:
                continue
            merged.append((start, end, etype, val))
        return merged

    def register_text(self, text: str) -> None:
        if not text:
            return
        for _start, _end, entity_type, original in self._collect_spans(text):
            self._token(entity_type, original)

    def anonymize(self, text: str) -> str:
        if not text or not self.reverse_map:
            return text
        out = text
        for value in sorted(self.reverse_map.keys(), key=len, reverse=True):
            out = out.replace(value, self.reverse_map[value])
        return out

    def anonymize_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        hygiene_added = False
        for msg in messages:
            role = msg.get("role", "")
            content = self.anonymize(msg.get("content", ""))
            if role == "system" and not hygiene_added and self.forward_map:
                content = f"{_PII_HYGIENE_LINE}\n\n{content}"
                hygiene_added = True
            out.append({**msg, "content": content})
        return out

    def restore(self, text: str) -> str:
        if not text:
            return text
        for token, original in self.forward_map.items():
            text = text.replace(token, original)
        return text

    def restore_stream_chunk(self, chunk: str) -> str:
        return self._stream_restorer.feed(chunk)

    def flush_stream(self) -> str:
        return self._stream_restorer.flush()


async def register_text_async(proxy: PIIProxy | None, text: str) -> None:
    if proxy is None or not text:
        return
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_get_executor(), proxy.register_text, text)


async def seed_pii_context(
    proxy: PIIProxy | None,
    *,
    query: str,
    document_context_block: str,
) -> None:
    if proxy is None:
        return
    await register_text_async(proxy, query)
    await register_text_async(proxy, document_context_block)


def batch_register_texts(proxy: PIIProxy | None, texts: list[str]) -> None:
    if proxy is None:
        return
    combined = "\n".join(t for t in texts if t)
    if combined:
        proxy.register_text(combined)


async def batch_register_for_synthesis(
    proxy: PIIProxy | None,
    *,
    hits: list[Any] | None = None,
    system_prompt: str | None = None,
    tabular_overlay: str | None = None,
    reduce_prompt: str | None = None,
    extra_texts: list[str] | None = None,
) -> None:
    if proxy is None:
        return
    texts: list[str] = []
    if hits:
        for h in hits:
            tc = getattr(h, "text_content", None) or (h.get("text_content") if isinstance(h, dict) else None)
            if tc:
                texts.append(tc)
    for block in (system_prompt, tabular_overlay, reduce_prompt):
        if block:
            texts.append(block)
    if extra_texts:
        texts.extend(extra_texts)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_get_executor(), batch_register_texts, proxy, texts)
