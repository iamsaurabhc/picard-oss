from __future__ import annotations

from typing import Any, Protocol

from app.schemas import SearchHit
from app.services.fts_search import FtsHit


class HitLike(Protocol):
    chunk_id: str
    document_id: str
    page_number: int
    text_content: str
    score: float


def trim_snippet_text(text: str, max_chars: int = 120) -> str:
    cleaned = (text or "").strip().replace("\n", " ")
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


class RetrievalProgressEmitter:
    MAX_SNIPPETS = 10
    SNIPPET_CHARS = 120

    def __init__(self, doc_names: dict[str, str] | None = None):
        self.doc_names = dict(doc_names or {})
        self._seen_chunks: set[str] = set()
        self._snippet_count = 0

    def update_doc_names(self, doc_names: dict[str, str]) -> None:
        self.doc_names.update(doc_names)

    def progress(self, phase: str, status: str, **detail: Any) -> dict:
        return {"event": "progress", "phase": phase, "status": status, **detail}

    def snippet_from_hit(self, hit: HitLike, source: str) -> dict | None:
        if self._snippet_count >= self.MAX_SNIPPETS:
            return None
        if hit.chunk_id in self._seen_chunks:
            return None
        text = trim_snippet_text(hit.text_content or "", self.SNIPPET_CHARS)
        if not text:
            return None
        self._seen_chunks.add(hit.chunk_id)
        self._snippet_count += 1
        return {
            "event": "snippet",
            "chunk_id": hit.chunk_id,
            "document_id": hit.document_id,
            "document_name": self.doc_names.get(hit.document_id, hit.document_id),
            "page_number": hit.page_number,
            "text": text,
            "source": source,
            "score": hit.score,
        }

    def best_hit(self, hits: list[FtsHit] | list[SearchHit]) -> FtsHit | SearchHit | None:
        if not hits:
            return None
        return min(hits, key=lambda h: h.score)


def consume_retrieval_generator(gen):
    """Drain a sync retrieval generator, returning (events, result)."""
    events: list[dict] = []
    try:
        while True:
            events.append(next(gen))
    except StopIteration as exc:
        if exc.value is None:
            raise RuntimeError("Retrieval generator finished without returning (hits, diagnostics)") from exc
        return events, exc.value
