"""Versioned legal RAG system prompts and contrastive exemplars (static, no eval KB retrieval)."""

from __future__ import annotations

# HelpV2-style precision preamble (paper Appendix A.2)
PREAMBLE_HELP_V2 = (
    "You are an accurate and reliable legal document assistant. "
    "Provide precise, evidence-backed responses using only the provided sources."
)

PREAMBLE_HELP_V1 = (
    "You are a truthful expert legal assistant. "
    "Answer correctly and concisely using only the provided sources."
)

CONTRASTIVE_BY_INTENT: dict[str, str] = {
    "factual_lookup": """
Example — GOOD (cite every fact):
**Son's name:** The infant son is Max Chester [1].
**Age:** He was aged 4 at the time of the accident [1].

Example — BAD (do not do this):
The son was about five years old. (No citation; invented age.)
""",
    "case_overview": """
Example — GOOD:
## Parties
The plaintiff is Chester; the defendant is Waverley Borough Council [1].

Example — BAD:
The case involves various parties and complex negligence issues. (Vague; no [N].)
""",
    "entity_matter_listing": """
Example — GOOD (one document section, cites from that doc only):
## Order-1737372538.pdf
- **Role of party:** Google LLC appears as opposite party [1].
- **Forum / statute:** Competition Commission of India, Section 4 [2].

Example — BAD (do not do this):
Google was involved in several CCI matters. (No filename section; no [N]; merges multiple docs.)
""",
    "entity_matter_listing_map": """
Example — GOOD (map brief for one document):
- **Role of party:** Respondent [1].
- **Key facts:** Informants alleged abuse of dominance [2].

Example — BAD:
The party appears in various proceedings. (No [N]; facts from other filenames.)
""",
    "entity_matter_listing_reduce": """
Example — GOOD (reduce from briefs only):
## Summary
Google LLC appears in 7 indexed documents across CCI proceedings.
## Order-A.pdf
(paste map brief bullets; keep [N] markers)

Example — BAD:
Combining all matters, Google violated competition law. (Cross-doc merge; ignores per-file sections.)
""",
    "general": """
Example — GOOD:
The claimed damages were £1,000 [1].

Example — BAD:
Damages were substantial. (Unsupported; no citation.)
""",
}


def preamble_for_variant(variant: str) -> str:
    v = (variant or "help_v2").casefold().replace("-", "_")
    if v in {"help_v1", "v1"}:
        return PREAMBLE_HELP_V1
    return PREAMBLE_HELP_V2


def contrastive_block(intent: str) -> str:
    return CONTRASTIVE_BY_INTENT.get(intent, CONTRASTIVE_BY_INTENT["general"]).strip()


def contrastive_block_for_listing_phase(phase: str) -> str:
    """Map/reduce listing phases use tighter contrastive exemplars."""
    key = f"entity_matter_listing_{phase}" if phase in {"map", "reduce"} else "entity_matter_listing"
    return CONTRASTIVE_BY_INTENT.get(key, CONTRASTIVE_BY_INTENT["entity_matter_listing"]).strip()
