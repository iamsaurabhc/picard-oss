from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExtractedMention:
    entity_type: str
    canonical_value: str
    display_value: str
    surface_text: str
    char_start: int | None
    char_end: int | None
    confidence: float = 1.0
    source: str = "rule"
