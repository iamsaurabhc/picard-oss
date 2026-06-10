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
Example — GOOD (one document section, substantive catalog):
## Order-1737372538.pdf
- **Role of party:** Google LLC and Google India Private Limited are opposite parties [1].
- **Forum / statute:** Competition Commission of India; Section 4 of the Competition Act [1].
- **Key facts:** CUTS filed alleging abuse of dominance in AdWords data practices [1].
- **Outcome / stage:** Investigation report finds opacity in advertiser metrics [1].

Example — BAD (do not do this):
Google was involved in several CCI matters. (No filename section; no [N]; merges multiple docs.)
""",
    "entity_matter_listing_map": """
Example — GOOD (map brief for one document — full identifiers):
- **Role of party:** Respondent / opposite party [1].
- **Case / matter id:** Case No. 30/2012 [1].
- **Forum / statute:** CCI; Section 4 [1].
- **Key facts:** Informants alleged search bias and entry barriers [2].
- **Outcome / stage:** Investigation ongoing as of order date [2].

Example — BAD:
The party appears in various proceedings. (No [N]; facts from other filenames.)
""",
    "entity_matter_listing_reduce": """
Example — GOOD (reduce with expanded per-file detail):
## Summary
Google LLC appears in 7 indexed documents across CCI Section 4 proceedings.
## Order-A.pdf
- **Parties:** CUTS (informant) v Google LLC (opposite party) [3][4].
- **Allegations:** Abuse of dominance via AdWords opacity [5].

Example — BAD:
Combining all matters, Google violated competition law. (Cross-doc merge; ignores per-file sections.)
""",
    "agent_entity_matter_listing": """
Example — GOOD (Agent mode — per-document catalog with substance):
## Summary
Google LLC and CUTS appear across 4 CCI orders spanning 2012–2014 abuse-of-dominance investigations [1].
## Order-30-2012.pdf
Google LLC is named as opposite party in Case No. 30/2012 before the Competition Commission of India [2].
Informants alleged contravention of Section 4 of the Competition Act [3]. The investigation was closed with no finding [4].

Example — BAD:
## Court & citation
Sources do not specify court. (Wrong template; skeleton sections; ignores excerpt content.)
""",
    "entity_matter_listing_map_agent": """
Example — GOOD (map brief — extract identifiers for reduce):
- **Case / matter id:** Case No. 30/2012 [1].
- **Forum / statute:** Competition Commission of India; Section 4 [2].
- **Dates / stage:** Order dated 12 March 2014; investigation closed [3].

Example — BAD:
Google was involved in competition matters. (No case number, forum, or date; no [N].)
""",
    "general": """
Example — GOOD:
The claimed damages were £1,000 [1].

Example — BAD:
Damages were substantial. (Unsupported; no citation.)

Example — GOOD (profile-driven playbook sections):
## Signatories
Authorized signatory Dyana Baurley (Director) for North American NDAs [1].

Example — BAD (wrong litigation skeleton on non-litigation doc):
## Court & citation
Sources do not specify court. (Ignores playbook excerpts; wrong template.)
""",
    "profile_synthesis": """
Example — GOOD (profile-driven sections from document profile):
## Signatories
Authorized signatory Dyana Baurley (Director) for North American NDAs [1].

## Preferred positions by topic
Standstill: 6-month term [2].
""",
}


def preamble_for_variant(variant: str) -> str:
    v = (variant or "help_v2").casefold().replace("-", "_")
    if v in {"help_v1", "v1"}:
        return PREAMBLE_HELP_V1
    return PREAMBLE_HELP_V2


def contrastive_block(intent: str) -> str:
    return CONTRASTIVE_BY_INTENT.get(intent, CONTRASTIVE_BY_INTENT["general"]).strip()


def contrastive_block_for_listing_phase(phase: str, *, agent_deep: bool = False) -> str:
    """Map/reduce listing phases use tighter contrastive exemplars."""
    if agent_deep and phase == "map":
        return CONTRASTIVE_BY_INTENT["entity_matter_listing_map_agent"].strip()
    if agent_deep:
        return CONTRASTIVE_BY_INTENT["agent_entity_matter_listing"].strip()
    key = f"entity_matter_listing_{phase}" if phase in {"map", "reduce"} else "entity_matter_listing"
    return CONTRASTIVE_BY_INTENT.get(key, CONTRASTIVE_BY_INTENT["entity_matter_listing"]).strip()
