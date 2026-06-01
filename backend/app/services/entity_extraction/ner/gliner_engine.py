from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

from app.config import settings
from app.services.entity_extraction.recognizers.rules import (
    normalize_amount,
    normalize_date,
    normalize_party,
)
from app.services.entity_extraction.types import ExtractedMention

logger = logging.getLogger(__name__)

GLINER_LABEL_TO_TYPE: dict[str, str] = {
    "person": "party",
    "organization": "party",
    "company": "party",
    "court": "party",
    "date": "date",
    "money": "amount",
    "contract": "identifier",
    "clause": "condition",
    "case number": "identifier",
}

PROSE_IDENTIFIER_BLOCKLIST = frozenset(
    {"agreement that", "agreement to", "the agreement", "agreement which"}
)


def model_dir() -> Path:
    return settings.picard_data_dir / "models" / settings.ner_model_name


def ner_available(*, require_enable_flag: bool = True) -> bool:
    if require_enable_flag and not settings.enable_ner_entity_extract:
        return False
    try:
        import gliner  # noqa: F401
    except ImportError:
        return False
    path = model_dir()
    return path.exists() or settings.ner_allow_hub_download


@lru_cache(maxsize=1)
def _load_model():
    from gliner import GLiNER

    path = model_dir()
    if path.exists():
        return GLiNER.from_pretrained(str(path))
    if settings.ner_allow_hub_download:
        model = GLiNER.from_pretrained(settings.ner_hub_model_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            model.save_pretrained(str(path))
        except Exception as exc:
            logger.warning("Could not cache GLiNER model to %s: %s", path, exc)
        return model
    raise FileNotFoundError(f"GLiNER model not found at {path}")


def _canonicalize(entity_type: str, surface: str) -> str | None:
    if entity_type == "date":
        return normalize_date(surface)
    if entity_type == "amount":
        return normalize_amount(surface)
    if entity_type == "identifier":
        canonical = surface.strip().casefold()
        if len(canonical) < 4:
            return None
        if canonical in PROSE_IDENTIFIER_BLOCKLIST:
            return None
        return canonical
    if entity_type in {"party", "condition"}:
        return normalize_party(surface)
    return surface.strip().casefold()


def extract_ner_mentions(
    text: str,
    labels: tuple[str, ...],
    *,
    threshold: float | None = None,
) -> list[ExtractedMention]:
    if not ner_available() or not text.strip():
        return []
    thresh = threshold if threshold is not None else settings.ner_threshold_low
    try:
        model = _load_model()
        predictions = model.predict_entities(
            text,
            list(labels),
            threshold=thresh,
            flat_ner=True,
        )
    except Exception as exc:
        logger.warning("GLiNER inference failed: %s", exc)
        return []

    mentions: list[ExtractedMention] = []
    for pred in predictions:
        label = (pred.get("label") or "").strip().casefold()
        entity_type = GLINER_LABEL_TO_TYPE.get(label)
        if not entity_type:
            continue
        surface = pred.get("text") or ""
        if not surface:
            continue
        score = float(pred.get("score") or 0.0)
        if score < settings.ner_threshold_low:
            continue
        canonical = _canonicalize(entity_type, surface)
        if not canonical:
            continue
        start = pred.get("start")
        end = pred.get("end")
        mentions.append(
            ExtractedMention(
                entity_type=entity_type,
                canonical_value=canonical,
                display_value=surface,
                surface_text=surface,
                char_start=int(start) if start is not None else None,
                char_end=int(end) if end is not None else None,
                confidence=score,
                source="ner",
            )
        )
    return mentions
