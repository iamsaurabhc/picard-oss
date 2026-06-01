from __future__ import annotations

from app.services.entity_extraction.types import ExtractedMention


def _overlaps(a: ExtractedMention, b: ExtractedMention) -> bool:
    if a.char_start is None or a.char_end is None or b.char_start is None or b.char_end is None:
        return False
    return a.char_start < b.char_end and b.char_start < a.char_end


def merge_mentions(
    rule_mentions: list[ExtractedMention],
    ner_mentions: list[ExtractedMention],
) -> list[ExtractedMention]:
    """Rule-wins on span overlap; NER fills non-overlapping gaps."""
    merged = list(rule_mentions)
    for ner in ner_mentions:
        if any(_overlaps(ner, rule) for rule in rule_mentions):
            continue
        merged.append(ner)
    return merged
