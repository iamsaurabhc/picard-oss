"""In-memory TTL cache for query embedding vectors."""

from __future__ import annotations

import time
from threading import Lock

from app.config import settings

_lock = Lock()
_cache: dict[tuple[str, str, str], tuple[float, list[float]]] = {}


def _normalize_query(q: str) -> str:
    return " ".join((q or "").split()).casefold()


def get_cached_query_embedding(
    query: str,
    *,
    workspace_id: str,
    model_id: str,
) -> list[float] | None:
    key = (workspace_id, model_id, _normalize_query(query))
    ttl = float(settings.query_expansion_cache_ttl_sec)
    now = time.monotonic()
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        ts, vec = entry
        if now - ts > ttl:
            _cache.pop(key, None)
            return None
        return vec


def set_cached_query_embedding(
    query: str,
    vec: list[float],
    *,
    workspace_id: str,
    model_id: str,
) -> None:
    key = (workspace_id, model_id, _normalize_query(query))
    with _lock:
        _cache[key] = (time.monotonic(), vec)


def clear_query_embedding_cache() -> None:
    with _lock:
        _cache.clear()
