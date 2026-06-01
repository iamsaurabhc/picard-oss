from __future__ import annotations

"""Rule-based entity recognizers (legacy).

Semantic org/party patterns are off the hot path when ENABLE_RULE_ENTITY_EXTRACT=false
and ENABLE_REGEX_NLP=false. Ingest uses extract_document_semantics (SLM) by default.
"""

import re

import dateparser

from app.services.entity_extraction.types import ExtractedMention

DATE_PATTERN = re.compile(
    r"\b(?:\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}[/.-]\d{1,2}[/.-]\d{1,2}|"
    r"\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{2,4})\b",
    re.IGNORECASE,
)
PARTY_PATTERN = re.compile(r"\bParty\s+([A-Z])\b", re.IGNORECASE)
_ORG_SUFFIX = r"(?:LLC|L\.?L\.?C\.?|Ltd\.?|Limited|Pvt\.?\s*Ltd\.?|Inc\.?|PLC)"
ORG_PARTY_PATTERN = re.compile(
    rf"\b((?:[A-Z][\w.&]+(?:\s+(?:[A-Z][\w.&]+|Private|Limited|Pvt)){{0,4}})\s+{_ORG_SUFFIX})\b",
)
_ORG_PARTY_START_DENY = frozenset(
    {
        "proceedings", "against", "under", "the", "in", "re", "section",
        "competition", "act", "informant", "informants", "commission",
    }
)
CONDITION_PATTERN = re.compile(r"\bCondition\s+([A-Z0-9]+)\b", re.IGNORECASE)
IDENTIFIER_PATTERN = re.compile(
    r"\b(?:CV|Case|Ref|Contract|Agreement)[-\s#:]?\s*[A-Z0-9-]{4,}\b",
    re.IGNORECASE,
)
AMOUNT_PATTERN = re.compile(r"£\s*[\d,]+(?:\.\d{2})?|\$\s*[\d,]+(?:\.\d{2})?", re.IGNORECASE)
LEGAL_ACTOR_PATTERN = re.compile(
    r"\b(?:the\s+)?(?:plaintiff|defendant|respondent|appellant)\b",
    re.IGNORECASE,
)
COURT_PATTERN = re.compile(
    r"\b(?:the\s+)?(?:(?:supreme|high|full)\s+court|court of appeal)\b",
    re.IGNORECASE,
)
TITLE_CASE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,4}\b")


def normalize_date(surface: str) -> str | None:
    parsed = dateparser.parse(surface, settings={"DATE_ORDER": "DMY"})
    if not parsed:
        return None
    return parsed.date().isoformat()


def normalize_party(surface: str) -> str:
    return surface.strip().casefold()


def normalize_condition(surface: str) -> str:
    m = CONDITION_PATTERN.search(surface)
    label = m.group(0) if m else surface
    return label.strip().casefold()


def normalize_amount(surface: str) -> str:
    cleaned = surface.strip().replace(",", "")
    if cleaned.startswith("£"):
        digits = re.sub(r"[^\d.]", "", cleaned)
        return f"{digits}_gbp" if digits else cleaned.casefold()
    if cleaned.startswith("$"):
        digits = re.sub(r"[^\d.]", "", cleaned)
        return f"{digits}_usd" if digits else cleaned.casefold()
    return cleaned.casefold()


def normalize_legal_actor(surface: str) -> str:
    s = re.sub(r"\s+", " ", surface.strip()).casefold()
    role = s.removeprefix("the ").strip()
    if role in {"plaintiff", "defendant", "respondent", "appellant"}:
        return f"the {role}"
    return s


def extract_rule_mentions(text: str, *, early_doc: bool) -> list[ExtractedMention]:
    mentions: list[ExtractedMention] = []
    for m in DATE_PATTERN.finditer(text):
        surface = m.group(0)
        canonical = normalize_date(surface)
        if canonical:
            mentions.append(
                ExtractedMention("date", canonical, surface, surface, m.start(), m.end())
            )
    for m in PARTY_PATTERN.finditer(text):
        surface = m.group(0)
        mentions.append(
            ExtractedMention("party", normalize_party(surface), surface, surface, m.start(), m.end())
        )
    for m in ORG_PARTY_PATTERN.finditer(text):
        surface = m.group(0).strip()
        first_token = surface.split()[0].casefold()
        if first_token in _ORG_PARTY_START_DENY:
            continue
        mentions.append(
            ExtractedMention("party", normalize_party(surface), surface, surface, m.start(), m.end())
        )
    for m in CONDITION_PATTERN.finditer(text):
        surface = m.group(0)
        mentions.append(
            ExtractedMention(
                "condition",
                normalize_condition(surface),
                surface,
                surface,
                m.start(),
                m.end(),
            )
        )
    for m in IDENTIFIER_PATTERN.finditer(text):
        surface = m.group(0)
        canonical = surface.strip().casefold()
        if not re.search(r"\d", canonical):
            continue
        mentions.append(
            ExtractedMention("identifier", canonical, surface, surface, m.start(), m.end())
        )
    for m in AMOUNT_PATTERN.finditer(text):
        surface = m.group(0)
        canonical = normalize_amount(surface)
        mentions.append(
            ExtractedMention("amount", canonical, surface, surface, m.start(), m.end())
        )
    for m in LEGAL_ACTOR_PATTERN.finditer(text):
        surface = m.group(0)
        mentions.append(
            ExtractedMention(
                "party",
                normalize_legal_actor(surface),
                surface,
                surface,
                m.start(),
                m.end(),
            )
        )
    for m in COURT_PATTERN.finditer(text):
        surface = m.group(0)
        mentions.append(
            ExtractedMention(
                "party",
                normalize_party(surface),
                surface,
                surface,
                m.start(),
                m.end(),
            )
        )
    if early_doc:
        for m in TITLE_CASE.finditer(text):
            surface = m.group(0)
            if surface.lower() in {"party a", "party b"}:
                continue
            if ORG_PARTY_PATTERN.search(surface):
                continue
            if len(surface.split()) >= 2:
                first = surface.split()[0].casefold()
                if first in _ORG_PARTY_START_DENY:
                    continue
                mentions.append(
                    ExtractedMention("party", normalize_party(surface), surface, surface, m.start(), m.end())
                )
    return mentions
