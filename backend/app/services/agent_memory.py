"""PicardMemory — procedural patterns via mem0 (Agent mode only)."""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import MemorySyncLog
from app.db.session import utc_now_iso
from app.services.model_router import _litellm_api_key, resolve_model

logger = logging.getLogger(__name__)

_MARKER_RE = re.compile(r"\[(\d+)\]")
_EXT_MARKER_RE = re.compile(r"\[ext:(\d+)\]", re.I)
_CHUNK_ID_RE = re.compile(r"chunk_[a-f0-9-]{8,}", re.I)


_MEMORY_NOISE = frozenset({"results", "result", "preferences", "preference", "memory", "memories"})


def memory_hit_useful(text: str) -> bool:
    """Filter mem0 hits that are too short or generic to show in the UI."""
    if not memory_store_allowed(text):
        return False
    stripped = text.strip()
    if len(stripped) < 16:
        return False
    lower = stripped.lower()
    if lower in _MEMORY_NOISE:
        return False
    words = lower.split()
    if len(words) <= 2 and all(w in _MEMORY_NOISE for w in words):
        return False
    return True


def memory_store_allowed(text: str) -> bool:
    """Reject legal conclusions and citation-bearing content (§4.2.11)."""
    if not text or not text.strip():
        return False
    stripped = text.strip()
    if len(stripped) > 2000:
        return False
    if _MARKER_RE.search(stripped) or _EXT_MARKER_RE.search(stripped):
        return False
    if _CHUNK_ID_RE.search(stripped):
        return False
    lower = stripped.lower()
    if "http://" in lower or "https://" in lower and "workflow" not in lower:
        if "prefer" not in lower and "process" not in lower:
            return False
    return True


def mem0_user_id(workspace_id: str, profile: str | None = None) -> str:
    return f"{workspace_id}:{profile or settings.agent_profile}"


class PicardMemory:
    """LightAgent CustomMemory adapter delegating to mem0."""

    def __init__(self, db: Session | None = None) -> None:
        self._db = db
        self._memory: Any = None

    def _ensure_client(self) -> Any:
        if self._memory is not None:
            return self._memory
        from mem0 import Memory

        settings.mem0_dir.mkdir(parents=True, exist_ok=True)
        api_key = _litellm_api_key()
        model = resolve_model()
        config: dict[str, Any] = {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "path": str(settings.mem0_dir / "qdrant"),
                    "on_disk": True,
                },
            },
        }
        if api_key and settings.llm_provider in {"openai", "anthropic"}:
            config["llm"] = {
                "provider": settings.llm_provider,
                "config": {
                    "model": model.replace("ollama/", ""),
                    "api_key": api_key,
                },
            }
        try:
            self._memory = Memory.from_config(config)
        except Exception:
            config["vector_store"] = {
                "provider": "chroma",
                "config": {"path": str(settings.mem0_dir / "chroma")},
            }
            self._memory = Memory.from_config(config)
        return self._memory

    def retrieve(self, query: str, user_id: str) -> list[str]:
        try:
            client = self._ensure_client()
            results = client.search(query, filters={"user_id": user_id}, top_k=5)
        except Exception as exc:
            logger.warning("mem0 retrieve failed: %s", exc)
            return []
        out: list[str] = []
        for item in results or []:
            if isinstance(item, dict):
                text = item.get("memory") or item.get("text") or ""
            else:
                text = str(item)
            if text and memory_hit_useful(text):
                out.append(text.strip())
        return out

    def store(self, data: str, user_id: str) -> bool:
        if not memory_store_allowed(data):
            return False
        if settings.mem0_max_entries > 0:
            try:
                client = self._ensure_client()
                existing = client.get_all(filters={"user_id": user_id})
                if existing and len(existing) >= settings.mem0_max_entries:
                    return False
            except Exception:
                pass
        try:
            client = self._ensure_client()
            client.add(data, user_id=user_id)
            self._log_sync(user_id, "add")
            return True
        except Exception as exc:
            logger.warning("mem0 store failed: %s", exc)
            return False

    def _log_sync(self, mem0_user_id: str, operation: str) -> None:
        if not self._db:
            return
        ws = mem0_user_id.split(":", 1)[0] if ":" in mem0_user_id else None
        row = MemorySyncLog(
            id=str(uuid.uuid4()),
            workspace_id=ws,
            mem0_user_id=mem0_user_id,
            operation=operation,
            created_at=utc_now_iso(),
        )
        self._db.add(row)
        self._db.commit()
