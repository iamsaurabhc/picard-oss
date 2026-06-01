from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractionProfile:
    doc_type: str
    ner_labels: tuple[str, ...]
    use_title_case_parties: bool = True


DEFAULT_NER_LABELS = (
    "person",
    "organization",
    "date",
    "money",
    "contract",
    "court",
)

CONTRACT_NER_LABELS = (
    "person",
    "organization",
    "date",
    "money",
    "contract",
    "clause",
)

LITIGATION_NER_LABELS = DEFAULT_NER_LABELS + ("case number",)

_PROFILES: dict[str, ExtractionProfile] = {
    "contract": ExtractionProfile("contract", CONTRACT_NER_LABELS),
    "nda": ExtractionProfile("nda", CONTRACT_NER_LABELS),
    "msa": ExtractionProfile("msa", CONTRACT_NER_LABELS),
    "lease": ExtractionProfile("lease", CONTRACT_NER_LABELS),
    "litigation": ExtractionProfile("litigation", LITIGATION_NER_LABELS),
    "regulatory": ExtractionProfile("regulatory", DEFAULT_NER_LABELS),
    "unknown": ExtractionProfile("unknown", DEFAULT_NER_LABELS),
}


def profile_for_doc_type(doc_type: str | None) -> ExtractionProfile:
    key = (doc_type or "unknown").strip().casefold()
    return _PROFILES.get(key, _PROFILES["unknown"])
