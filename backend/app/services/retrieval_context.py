"""Request-scoped caches for retrieval (page chunks, FTS scores, vector scores)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RetrievalContext:
    page_chunk_cache: dict[tuple[str, int], list] = field(default_factory=dict)
    fts_page_scores_cache: dict[tuple[str, str], dict[int, float]] = field(default_factory=dict)
    page_vector_scores_cache: dict[tuple[str, str], dict[int, float]] = field(default_factory=dict)
    chunk_vector_search_cache: dict[tuple[str, str, str], list] = field(default_factory=dict)


_request_ctx: RetrievalContext | None = None


def get_retrieval_context() -> RetrievalContext:
    global _request_ctx
    if _request_ctx is None:
        _request_ctx = RetrievalContext()
    return _request_ctx


def reset_retrieval_context() -> None:
    global _request_ctx
    _request_ctx = RetrievalContext()


def clear_retrieval_context() -> None:
    global _request_ctx
    _request_ctx = None
