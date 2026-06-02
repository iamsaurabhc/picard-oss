from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.schemas import TabularColumn

ColumnFormat = Literal[
    "text",
    "bulleted_list",
    "number",
    "currency",
    "yes_no",
    "date",
    "tag",
    "percentage",
    "monetary_amount",
]

_PARTIES_PROMPT = (
    "List every party to this matter. Include applicants, respondents, informants, "
    "opposite parties, petitioners, and any company or authority named as a party in the "
    "caption, cause title, or first pages. For each, state full legal name and role. "
    "One party per bullet. Do not answer \"Not specified\" if any party name appears "
    "in the provided chunks or indexed party list."
)


@dataclass(frozen=True)
class RetrievalPolicy:
    strategies: tuple[str, ...]
    early_page_count: int = 5
    max_chunks: int = 8
    entity_types: tuple[str, ...] = ("party",)
    fts_seed_query: str | None = None
    heading_hint: str | None = None


DEFAULT_RETRIEVAL = RetrievalPolicy(strategies=("early_pages", "fts"), max_chunks=8)

RETRIEVAL_BY_KEY: dict[str, RetrievalPolicy] = {
    "parties": RetrievalPolicy(
        strategies=("early_pages", "entity_index", "fts"),
        early_page_count=5,
        max_chunks=8,
        entity_types=("party",),
    ),
    "governing_law": RetrievalPolicy(
        strategies=("early_pages", "fts"),
        early_page_count=5,
        max_chunks=8,
        fts_seed_query="jurisdiction OR governing OR statute OR Competition Act OR Act India",
    ),
    "effective_date": RetrievalPolicy(
        strategies=("early_pages", "entity_index", "fts"),
        early_page_count=5,
        max_chunks=8,
        entity_types=("date",),
        fts_seed_query="order dated OR dated OR effective OR commencement",
    ),
    "termination": RetrievalPolicy(
        strategies=("fts",),
        max_chunks=6,
        heading_hint="terminat",
    ),
    "confidentiality": RetrievalPolicy(
        strategies=("fts",),
        max_chunks=6,
        heading_hint="confidential",
    ),
}

DOC_TYPE_PROMPTS: dict[str, dict[str, str]] = {
    "governing_law": {
        "regulatory": (
            "State the applicable statute and/or jurisdiction for this regulatory order "
            '(e.g. "Competition Act 2002, India" or "CCI, India"). If only procedural jurisdiction, '
            'state that briefly. If truly absent, write "Not specified".'
        ),
        "litigation": (
            "State court jurisdiction or governing procedural law if stated in the caption or first pages. "
            'Otherwise "Not specified". Max 2 sentences.'
        ),
    },
    "effective_date": {
        "regulatory": (
            "State the order date or investigation commencement date from the caption or first pages "
            'in DD Mon YYYY format only. If absent, write "Not specified".'
        ),
        "litigation": (
            "State filing date or order date from caption if present (DD Mon YYYY only). "
            'Otherwise "Not specified".'
        ),
    },
    "termination": {
        "regulatory": (
            "Summarize order provisions on account suspension, closure, or investigation termination "
            "in 1-2 sentences maximum. Focus on the order, not commercial contract termination."
        ),
    },
    "confidentiality": {
        "regulatory": (
            "Summarize confidentiality of investigation filings or DG submissions in 1-2 sentences. "
            "Include duration if stated."
        ),
    },
}


def retrieval_policy_for_column(column_key: str) -> RetrievalPolicy:
    return RETRIEVAL_BY_KEY.get(column_key, DEFAULT_RETRIEVAL)


def prompt_for_column(column: TabularColumn, doc_type: str | None) -> str:
    if doc_type and column.key in DOC_TYPE_PROMPTS:
        variant = DOC_TYPE_PROMPTS[column.key].get(doc_type)
        if variant:
            return variant
    return column.prompt


def regulatory_dd_columns() -> list[TabularColumn]:
    return [
        TabularColumn(key="parties", label="Parties", format="bulleted_list", prompt=_PARTIES_PROMPT),
        TabularColumn(
            key="governing_law",
            label="Statute / Jurisdiction",
            format="text",
            prompt=DOC_TYPE_PROMPTS["governing_law"]["regulatory"],
        ),
        TabularColumn(
            key="effective_date",
            label="Order Date",
            format="date",
            prompt=DOC_TYPE_PROMPTS["effective_date"]["regulatory"],
        ),
        TabularColumn(
            key="confidentiality",
            label="Confidentiality of Filing",
            format="text",
            prompt=DOC_TYPE_PROMPTS["confidentiality"]["regulatory"],
        ),
        TabularColumn(
            key="termination",
            label="Suspension / Closure",
            format="text",
            prompt=DOC_TYPE_PROMPTS["termination"]["regulatory"],
        ),
    ]


@dataclass(frozen=True)
class ColumnPreset:
    key: str
    label: str
    format: ColumnFormat
    prompt: str
    pattern: re.Pattern[str]
    tag_options: tuple[str, ...] = ()


PROMPT_PRESETS: list[ColumnPreset] = [
    ColumnPreset(
        key="parties",
        label="Parties",
        format="bulleted_list",
        pattern=re.compile(r"\bpart(y|ies)\b", re.I),
        prompt=_PARTIES_PROMPT,
    ),
    ColumnPreset(
        key="governing_law",
        label="Governing Law",
        format="text",
        pattern=re.compile(r"\bgoverning law\b|\bjurisdiction\b", re.I),
        prompt=(
            'State only the governing law using the short-form jurisdiction name, '
            'e.g. "New York Law", "English Law". If not specified, write "Not specified".'
        ),
    ),
    ColumnPreset(
        key="effective_date",
        label="Effective Date",
        format="date",
        pattern=re.compile(r"\beffective date\b", re.I),
        prompt=(
            'State only the effective date in DD Mon YYYY format. '
            'If not explicitly stated, write "Not specified".'
        ),
    ),
    ColumnPreset(
        key="term",
        label="Term",
        format="text",
        pattern=re.compile(r"\bterm\b|\bduration\b", re.I),
        prompt=(
            'State only the duration or term in concise form, e.g. "3 years", "24 months", "perpetual".'
        ),
    ),
    ColumnPreset(
        key="termination",
        label="Termination",
        format="text",
        pattern=re.compile(r"\bterminat(e|ion|ing)\b", re.I),
        prompt=(
            "Extract termination provisions: who may terminate, triggers, notice period, "
            "cure period, and key consequences. Be concise (max 2 sentences)."
        ),
    ),
    ColumnPreset(
        key="change_of_control",
        label="Change of Control",
        format="text",
        pattern=re.compile(r"\bchange of control\b", re.I),
        prompt=(
            "Identify change of control provisions: triggers, consequences, consent requirements. "
            "Be concise (max 2 sentences)."
        ),
    ),
    ColumnPreset(
        key="confidentiality",
        label="Confidentiality",
        format="text",
        pattern=re.compile(r"\bconfidential(ity)?\b|\bnon-?disclosure\b", re.I),
        prompt=(
            "Summarize confidentiality obligations in max 2 sentences: scope, exceptions, duration."
        ),
    ),
    ColumnPreset(
        key="assignment",
        label="Assignment",
        format="yes_no",
        pattern=re.compile(r"\bassign(ment|ability)?\b", re.I),
        prompt="Is assignment of this agreement permitted without the other party's consent?",
    ),
]


def match_preset(label: str) -> ColumnPreset | None:
    trimmed = label.strip()
    if not trimmed:
        return None
    for preset in PROMPT_PRESETS:
        if preset.pattern.search(trimmed):
            return preset
    return None


def preset_prompt_for_label(label: str) -> str | None:
    preset = match_preset(label)
    return preset.prompt if preset else None


def column_key_from_label(label: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    return key or "column"
