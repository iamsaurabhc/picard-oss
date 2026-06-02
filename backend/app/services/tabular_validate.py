from __future__ import annotations

import re

from app.schemas import TabularColumn
from app.services.tabular_grounding import metadata_summary_misses

CellFlag = str

CONTRACT_ONLY_COLUMNS = frozenset({"governing_law", "termination", "confidentiality", "term", "assignment"})

FORMAT_MAX_WORDS: dict[str, int] = {
    "bulleted_list": 120,
    "date": 15,
    "yes_no": 6,
    "text": 60,
    "number": 20,
    "currency": 20,
    "tag": 30,
    "percentage": 15,
    "monetary_amount": 25,
}


def is_litigation_na_column(doc_type: str | None, column_key: str) -> bool:
    if doc_type != "litigation":
        return False
    return column_key in CONTRACT_ONLY_COLUMNS


def litigation_na_summary(column_key: str) -> str:
    return "N/A — litigation pleading (not a contract)"


def format_instruction(fmt: str) -> str:
    rules = {
        "bulleted_list": "summary MUST be at most 8 bullet lines starting with '- '; no paragraph prose.",
        "date": 'summary MUST be a single date in DD Mon YYYY format OR exactly "Not specified" (max 15 words).',
        "yes_no": 'summary MUST be exactly "Yes", "No", or "Not specified" — one value only.',
        "text": "summary MUST be at most 2 short sentences or 40 words total.",
    }
    return rules.get(fmt, rules["text"])


def enforce_format_summary(summary: str, fmt: str) -> str:
    text = (summary or "").strip()
    max_words = FORMAT_MAX_WORDS.get(fmt, 60)
    words = text.split()
    if len(words) <= max_words:
        return text

    if fmt == "bulleted_list":
        lines = [ln.strip() for ln in re.split(r"[\n•]+", text) if ln.strip()]
        trimmed: list[str] = []
        word_count = 0
        for line in lines[:8]:
            line_words = line.split()
            if word_count + len(line_words) > max_words:
                break
            trimmed.append(line if line.startswith("-") else f"- {line}")
            word_count += len(line_words)
        return "\n".join(trimmed) if trimmed else " ".join(words[:max_words])

    if fmt == "date":
        date_match = re.search(
            r"\b(\d{1,2}\s+\w{3,9}\s+\d{4}|\d{4}-\d{2}-\d{2})\b",
            text,
        )
        if date_match:
            return date_match.group(1)
        if "not specified" in text.casefold():
            return "Not specified"
        return " ".join(words[:max_words])

    if fmt == "yes_no":
        lower = text.casefold()
        if lower.startswith("yes"):
            return "Yes"
        if lower.startswith("no"):
            return "No"
        return "Not specified"

    return " ".join(words[:max_words]) + ("…" if len(words) > max_words else "")


def needs_shorter_retry(summary: str, column: TabularColumn) -> bool:
    max_words = FORMAT_MAX_WORDS.get(column.format, 60)
    return len((summary or "").split()) > int(max_words * 1.25)


def needs_metadata_retry(
    summary: str,
    column_key: str,
    metadata: dict[str, str],
) -> bool:
    if column_key not in ("governing_law", "effective_date"):
        return False
    return metadata_summary_misses(summary, metadata)
