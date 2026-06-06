from __future__ import annotations

import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.services.document_context import DocumentContext, build_document_context
from app.services.entity_index import (
    normalize_amount,
    normalize_party,
    resolve_party_canonicals,
)
from app.services.model_router import ModelRole, completion
from app.services.prompt_registry import get_prompt

logger = logging.getLogger(__name__)

Intent = Literal[
    "case_overview",
    "entity_matter_listing",
    "case_context",
    "timeline",
    "obligations",
    "factual_lookup",
    "general",
]
RetrievalMode = Literal["SIMPLE", "MULTI_CONSTRAINT"]

DEFAULT_OVERVIEW_FACETS = [
    "parties", "central_facts", "damages", "dates", "court", "outcome",
]

# Generic legal dimensions — no corpus-specific tokens
DEFAULT_FACET_QUERIES: dict[str, list[str]] = {
    "parties": ["plaintiff", "defendant", "informant"],
    "central_facts": ["facts", "occurred", "alleged"],
    "damages": ["damages", "claimed", "relief"],
    "dates": ["date", "trial", "filed"],
    "court": ["court", "jurisdiction", "commission"],
    "outcome": ["judgment", "appeal", "order"],
}

INTENT_KEYWORDS = {
    "case_overview": [
        "list all",
        "overview",
        "summarize the case",
        "summarise the case",
        "tell me about the case",
        "what is this case about",
        "background of the case",
        "parties and",
        "complete overview",
    ],
    "case_context": ["case context", "context for", "matter context"],
    "timeline": ["timeline", "chronology", "when did", "sequence of events"],
    "obligations": ["obligations", "duties", "requirements under"],
    "factual_lookup": [
        "what damages",
        "what sum",
        "how much",
        "who is",
        "which party",
        "amount claimed",
        "amount sought",
        "damages claimed",
        "damages sought",
    ],
}


class FtsPlan(BaseModel):
    must_terms: list[str] = Field(default_factory=list)
    should_terms: list[str] = Field(default_factory=list)
    phrases: list[str] = Field(default_factory=list)
    operator: Literal["AND", "OR"] = "AND"


class QueryConstraint(BaseModel):
    type: str
    canonical: str
    surfaces: list[str] = Field(default_factory=list)


class SearchPass(BaseModel):
    label: str
    fts_terms: list[str] = Field(default_factory=list)
    operator: Literal["AND", "OR"] = "AND"
    pin_best: bool = True


class SubQuestion(BaseModel):
    label: str
    question: str
    fts_terms: list[str] = Field(default_factory=list)
    operator: Literal["AND", "OR"] = "AND"
    pin_best: bool = True


class TargetEntity(BaseModel):
    canonical: str
    surfaces: list[str] = Field(default_factory=list)
    resolved_canonicals: list[str] = Field(default_factory=list)


class QueryUnderstanding(BaseModel):
    retrieval_mode: RetrievalMode = "SIMPLE"
    intent: Intent = "general"
    target_entity: TargetEntity | None = None
    constraints: list[QueryConstraint] = Field(default_factory=list)
    fts: FtsPlan = Field(default_factory=FtsPlan)
    metadata_filters: dict[str, str] = Field(default_factory=dict)
    overview_facets: list[str] = Field(default_factory=list)
    facet_queries: dict[str, list[str]] = Field(default_factory=dict)
    search_passes: list[SearchPass] = Field(default_factory=list)
    sub_questions: list[SubQuestion] = Field(default_factory=list)
    coverage_goal: str = ""
    confidence: float = 0.5
    used_llm: bool = False
    rule_merges: list[str] = Field(default_factory=list)
    pass_repairs: list[str] = Field(default_factory=list)


QUERY_PLANNER_PROMPT = """Analyze this legal document search question and plan retrieval passes.
Return JSON only:
{{
  "retrieval_mode": "SIMPLE" | "MULTI_CONSTRAINT",
  "intent": "case_overview" | "entity_matter_listing" | "case_context" | "timeline" | "obligations" | "factual_lookup" | "general",
  "target_entity": {{"canonical": "google llc", "surfaces": ["Google LLC"]}} or null,
  "constraints": [{{"type": "party|date|condition|identifier|amount", "canonical": "...", "surfaces": ["..."]}}],
  "fts": {{
    "must_terms": ["anchor terms for first pass"],
    "should_terms": [],
    "phrases": [],
    "operator": "AND" | "OR"
  }},
  "sub_questions": [
    {{
      "label": "short_label",
      "question": "restated sub-question",
      "fts_terms": ["doc_vocab_term1", "doc_vocab_term2"],
      "operator": "AND",
      "pin_best": true
    }}
  ],
  "search_passes": [
    {{"label": "short_label", "fts_terms": ["term1", "term2"], "operator": "AND", "pin_best": true}}
  ],
  "coverage_goal": "broad matter summary | pinpoint fact | relevant passages",
  "confidence": 0.0-1.0
}}

{document_context}

Rules:
- Use vocabulary from the document context previews, parties, entities, and headings — not generic legal clichés.
- For compound questions (multiple ? or distinct sub-topics): emit one sub_question AND one search_pass per sub-part.
- Each search_pass uses exactly 2 FTS terms (AND by default). Never use question-framing words as terms (name, date, what, when, who, how, age).
- Use entity_matter_listing when the user wants all cases/matters against or involving a named party (e.g. list all cases against Google LLC). Set target_entity with canonical (lowercase) and surfaces.
- For entity_matter_listing: emit 4–6 search_passes for distinct per-document dimensions the user needs (parties/counterparties, filing/allegations, forum/statute, outcome/stage). Derive every fts_term from document context previews, parties, entities, or headings — never generic placeholders.
- Use case_overview when the user wants a broad summary of one named case (X v Y, list all case details involving a single matter). target_entity should be null.
- Emit a party constraint matching target_entity when intent is entity_matter_listing.
- For case_overview: emit 4–8 search_passes for distinct dimensions visible in this document.
- MULTI_CONSTRAINT only when ≥2 typed constraints AND intent is case_context/timeline/obligations.
- For amount constraints: only when normalized (e.g. "1000_gbp"). Never free-text amount canonicals.
- Populate sub_questions for factual_lookup and compound factual queries.

Question: {query}"""


_STOPWORDS = frozenset(
    {
        "a", "an", "and", "by", "did", "do", "for", "how", "in", "is", "of", "or", "the", "to",
        "was", "were", "what", "when", "where", "which", "who",
        "list", "all", "any", "involving", "about", "regarding", "concerning",
        "details", "detail", "show", "find", "give", "tell", "explain", "describe",
        "case", "facts", "claim",
    }
)

_VALID_INTENTS: frozenset[str] = frozenset({
    "case_overview",
    "entity_matter_listing",
    "case_context",
    "timeline",
    "obligations",
    "factual_lookup",
    "general",
})

_LISTING_QUERY_HINTS = frozenset({"against", "involving", "re"})
_LISTING_SCOPE_HINTS = frozenset({"cases", "matters", "proceedings", "complaints", "documents"})

_AMOUNT_CANONICAL_RE = re.compile(r"^\d+(?:\.\d+)?_(?:gbp|usd)$")

_QUESTION_FRAMING_WORDS = frozenset(
    {
        "name", "age", "date", "old", "called", "what", "when", "where", "who", "how",
        "accident", "incident", "happened", "occurred", "time",
    }
)

_CASE_QUERY_FRAMING = frozenset(
    {
        "list", "all", "case", "details", "detail", "on", "the", "involving", "about",
        "show", "give", "tell",
    }
)


def _is_valid_amount_canonical(canonical: str) -> bool:
    return bool(_AMOUNT_CANONICAL_RE.match(canonical))


_LISTING_ENTITY_RE = re.compile(
    r"\b(?:against|involving|re)\s+(.+?)(?:\?|$)",
    re.IGNORECASE,
)


def _is_entity_matter_listing_query(query: str) -> bool:
    if not settings.enable_regex_nlp:
        return _looks_like_entity_listing_query(query)
    q = query.casefold()
    if re.search(
        r"\blist\s+all\s+.*\bcase\s+details?\s+(?:against|involving|re)\b",
        q,
    ):
        return True
    if re.search(r"\blist\s+all\b", q) and re.search(
        r"\bcase\s+details?\s+(?:against|involving|re)\b", q
    ):
        return True
    if _case_name_terms(query) and not re.search(
        r"\b(?:cases|matters|proceedings|complaints)\s+(?:against|involving|re)\b", q
    ):
        if not re.search(r"\bcase\s+details?\s+(?:against|involving|re)\b", q):
            return False
    if re.search(
        r"\blist\s+all\s+(?:the\s+)?(?:cases|matters|proceedings|complaints|documents)\b"
        r".*\b(?:against|involving|re)\b",
        q,
    ):
        return True
    if re.search(r"\b(?:cases|matters|proceedings|complaints)\s+(?:against|involving|re)\s+", q):
        return True
    if re.search(r"\ball\s+documents\s+(?:mentioning|involving)\s+", q):
        return True
    if re.search(r"\blist\b", q) and re.search(r"\b(?:cases|matters)\b", q) and re.search(
        r"\b(?:against|involving)\b", q
    ):
        return True
    if re.search(r"\blist\s+all\s+.*\bcase\s+details?\s+against\b", q):
        return True
    return False


def _looks_like_entity_listing_query(query: str) -> bool:
    """Keyword hints for catalog fallback — not regex intent classifiers."""
    q = query.casefold()
    if re.search(r"\s+v\.?\s+", query, re.IGNORECASE):
        if not any(h in q for h in _LISTING_SCOPE_HINTS):
            return False
    if not any(h in q for h in _LISTING_SCOPE_HINTS):
        return False
    return any(h in q for h in _LISTING_QUERY_HINTS) or ("list" in q and "all" in q)


def _party_from_filed_by_phrase(query: str) -> QueryConstraint | None:
    """Extract informant/filer after 'filed by' (e.g. case details filed by Kshitiz Arya in CCI)."""
    m = re.search(
        r"\bfiled\s+by\s+(.+?)(?:\s+in\s+|\s+at\s+|\s+before\s+|\s+with\s+|\?|$)",
        query,
        re.IGNORECASE,
    )
    if not m:
        return None
    surface = re.sub(r"\s+", " ", m.group(1).strip(" ?.,;"))
    if len(surface) < 3:
        return None
    return QueryConstraint(
        type="party",
        canonical=normalize_party(surface),
        surfaces=[surface],
    )


def _party_from_listing_phrase(query: str) -> QueryConstraint | None:
    """Extract party after against/involving without ORG_PARTY_PATTERN."""
    q = query.casefold()
    if "case details" in q or "case detail" in q:
        return None
    for marker in ("against ", "involving ", "re "):
        if marker in q:
            idx = q.index(marker) + len(marker)
            surface = re.sub(r"\s+", " ", query[idx:].strip(" ?.,;"))
            if len(surface) >= 3:
                return QueryConstraint(
                    type="party",
                    canonical=normalize_party(surface),
                    surfaces=[surface],
                )
    return None


def _catalog_party_constraint(
    db: Session,
    workspace_id: str,
    query: str,
) -> QueryConstraint | None:
    """Match workspace party entities by token overlap (no ORG_PARTY_PATTERN)."""
    from app.db.models import Entity

    tokens = set(_extract_tokens(query))
    if not tokens:
        return None
    best: Entity | None = None
    best_score = 0
    for entity in db.scalars(
        select(Entity).where(
            Entity.workspace_id == workspace_id,
            Entity.entity_type == "party",
        )
    ).all():
        cv = entity.canonical_value
        dv = entity.display_value.casefold()
        cv_tokens = set(cv.split())
        dv_tokens = set(dv.split())
        overlap = len(tokens & cv_tokens) + len(tokens & dv_tokens)
        for t in tokens:
            if len(t) >= 3 and (t in cv or t in dv):
                overlap += 1
        if overlap > best_score:
            best_score = overlap
            best = entity
    if best is None or best_score < 1:
        return None
    return QueryConstraint(
        type="party",
        canonical=best.canonical_value,
        surfaces=[best.display_value],
    )


def _parse_target_entity(data: object) -> TargetEntity | None:
    if not isinstance(data, dict):
        return None
    canonical = str(data.get("canonical") or "").strip().casefold()
    if not canonical:
        return None
    surfaces = [str(s).strip() for s in (data.get("surfaces") or []) if str(s).strip()]
    if not surfaces:
        surfaces = [canonical.title()]
    return TargetEntity(canonical=canonical, surfaces=surfaces)


def _extract_listing_target_entity(query: str) -> QueryConstraint | None:
    if not settings.enable_regex_nlp:
        return None
    from app.services.entity_index import ORG_PARTY_PATTERN

    for m in ORG_PARTY_PATTERN.finditer(query):
        surface = m.group(0).strip()
        canonical = normalize_party(surface)
        return QueryConstraint(type="party", canonical=canonical, surfaces=[surface])
    match = _LISTING_ENTITY_RE.search(query)
    if match:
        surface = re.sub(r"\s+", " ", match.group(1).strip(" .,;"))
        if len(surface) >= 3:
            canonical = normalize_party(surface)
            return QueryConstraint(type="party", canonical=canonical, surfaces=[surface])
    return None


def _extract_listing_v_party_constraints(query: str) -> list[QueryConstraint]:
    """Both parties from 'involving X v Y' listing queries (e.g. Google v CUTS)."""
    if not re.search(r"\binvolving\b", query, re.IGNORECASE):
        return []
    if not re.search(r"\s+v\.?\s+", query, re.IGNORECASE):
        return []
    parts = re.split(r"\s+v\.?\s+", query, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) != 2:
        return []
    left = re.sub(r"\s+", " ", parts[0].strip())
    q_left = left.casefold()
    for marker in ("involving ", "against ", "re "):
        if marker in q_left:
            idx = q_left.index(marker) + len(marker)
            left = left[idx:].strip()
            break
    right = re.sub(r"\s+", " ", parts[1].strip(" ?.,;"))
    out: list[QueryConstraint] = []
    for surface in (left, right):
        if len(surface) >= 3:
            out.append(
                QueryConstraint(
                    type="party",
                    canonical=normalize_party(surface),
                    surfaces=[surface],
                )
            )
    return out


def _is_case_overview_query(query: str) -> bool:
    if not settings.enable_regex_nlp:
        return False
    if _is_entity_matter_listing_query(query):
        return False
    q = query.casefold()
    if any(kw in q for kw in INTENT_KEYWORDS["case_overview"]):
        return True
    if re.search(r"\blist\b.*\b(case|details)\b", q):
        return True
    if re.search(r"\bcase\s+details\b", q) and re.search(r"\b(list|all|overview|summar)", q):
        if re.search(r"\bagainst\b", q) and not re.search(r"\s+v\.?\s+", query, re.IGNORECASE):
            return False
        return True
    if re.search(r"\bcase\s+details\b", q) and re.search(r"\binvolving\b", q):
        if re.search(r"\blist\s+all\b", q):
            return False
        return True
    if re.search(r"\bcase\s+details\b.*\bfiled\s+by\b", q):
        return True
    return False


def _is_factual_amount_query(query: str) -> bool:
    q = query.casefold()
    if re.search(r"\b(amount|damages|sum)\s+(claimed|sought)\b", q):
        return True
    if re.search(r"\b(claimed|sought)\s+(amount|damages|sum)\b", q):
        return True
    if re.search(r"\bhow much\b", q):
        return True
    return False


def _is_factual_lookup_query(query: str) -> bool:
    if _is_factual_amount_query(query):
        return True
    q = query.casefold()
    if re.search(r"\b(what is|what was|what are|who is|who was|when did|when was|how old|date of)\b", q):
        return True
    if "?" in query and not _is_case_overview_query(query):
        if re.search(r"\b(name|age|date|accident|incident|when|who|how)\b", q):
            return True
        if query.count("?") >= 2:
            return True
    return False


def _fallback_intent(query: str) -> Intent:
    """Regex intent heuristic — only when enable_regex_nlp."""
    if not settings.enable_regex_nlp:
        return "general"
    if _is_entity_matter_listing_query(query):
        return "entity_matter_listing"
    if _is_case_overview_query(query):
        return "case_overview"
    if _is_factual_lookup_query(query):
        return "factual_lookup"
    q = query.casefold()
    if any(kw in q for kw in INTENT_KEYWORDS["factual_lookup"]):
        return "factual_lookup"
    if query.count("?") >= 2:
        return "factual_lookup"
    return "general"


def _classify_intent(query: str) -> Intent:
    return _fallback_intent(query)


def _default_facet_queries(case_terms: list[str] | None = None) -> dict[str, list[str]]:
    queries = {k: list(v) for k, v in DEFAULT_FACET_QUERIES.items()}
    if case_terms:
        queries["parties"] = _dedupe_terms(queries["parties"] + case_terms[:2])
    return queries


def _passes_from_facet_queries(facet_queries: dict[str, list[str]]) -> list[SearchPass]:
    return [
        SearchPass(label=label, fts_terms=terms[:2], operator="AND", pin_best=True)
        for label, terms in facet_queries.items()
        if terms
    ]


def _facet_queries_from_passes(passes: list[SearchPass]) -> dict[str, list[str]]:
    return {p.label: list(p.fts_terms) for p in passes if p.fts_terms}


def _fallback_search_passes(
    query: str,
    intent: Intent,
    case_terms: list[str] | None = None,
    *,
    party_constraint: QueryConstraint | None = None,
) -> list[SearchPass]:
    """Generic token FTS fallback — no corpus-specific term maps."""
    tokens = _extract_tokens(query)
    case_terms = case_terms or _case_name_terms(query) or []

    if _is_factual_amount_query(query):
        return [
            SearchPass(label="amount", fts_terms=["damages", "claimed"], operator="AND", pin_best=False),
        ]

    if intent == "entity_matter_listing":
        entity = party_constraint
        if entity is None and settings.enable_regex_nlp:
            entity = _extract_listing_target_entity(query)
        if entity:
            terms = _dedupe_terms(_extract_tokens(entity.surfaces[0]) + entity.surfaces[0].split()[:2])
            terms = [t.casefold() for t in terms if len(t) > 2][:2]
            if terms:
                return [SearchPass(label="entity_anchor", fts_terms=terms, operator="AND", pin_best=False)]
        tokens = _extract_tokens(query)
        clean = [t for t in tokens if t not in _QUESTION_FRAMING_WORDS]
        if clean:
            return [SearchPass(label="entity_anchor", fts_terms=clean[:2], operator="AND", pin_best=False)]
        return []

    if intent == "case_overview":
        facets = _default_facet_queries(case_terms)
        return _passes_from_facet_queries(facets)

    if case_terms:
        return [SearchPass(label="anchor", fts_terms=case_terms[:2], operator="AND", pin_best=False)]

    clean = [t for t in tokens if t not in _QUESTION_FRAMING_WORDS]
    terms = clean[:2] if clean else tokens[:2]
    if terms:
        return [SearchPass(label="fallback", fts_terms=terms, operator="AND", pin_best=False)]
    return []


def _should_use_case_overview_not_listing(query: str, case_terms: list[str] | None) -> bool:
    """'List case details on Winzo v Google' is one matter, not a catalog against Google."""
    if not case_terms:
        return False
    q = query.casefold()
    if re.search(r"\blist\s+all\b", q) and re.search(
        r"\bcase\s+details?\s+(?:against|involving|re)\b", q
    ):
        return False
    if re.search(r"\blist\s+all\b", q) and re.search(
        r"\b(?:cases|matters|proceedings|complaints)\s+(?:against|involving|re)\b", q
    ):
        return False
    if not re.search(r"\b(?:case\s+details?|matter\s+details?)\b", q):
        return False
    if re.search(r"\b(?:cases|matters|proceedings|complaints)\s+(?:against|involving|re)\b", q):
        return False
    # "case details against Google" = catalog of matters vs Google, not one "X v Y" case.
    if re.search(r"\bcase\s+details?\s+against\b", q):
        return False
    if re.search(r"\b(?:against|involving|re)\s+", q) and not re.search(
        r"\s+v\.?\s+", query, re.IGNORECASE
    ):
        return False
    return bool(re.search(r"\s+v\.?\s+", query, re.IGNORECASE))


def _validate_retrieval_plan(
    understanding: QueryUnderstanding,
    query: str,
    *,
    used_llm: bool,
) -> QueryUnderstanding:
    """Schema validation and safety — no regex intent overrides or pass merging."""
    merges: list[str] = list(understanding.rule_merges)
    case_terms = _case_name_terms(query) or understanding.fts.must_terms[:2]

    if (
        understanding.intent == "entity_matter_listing"
        and _should_use_case_overview_not_listing(query, case_terms)
    ):
        understanding.intent = "case_overview"
        understanding.target_entity = None
        merges.append("intent:listing_to_overview:case_v_pattern")

    valid_constraints: list[QueryConstraint] = []
    amount_fts_boost: list[str] = []
    for c in understanding.constraints:
        if c.type == "amount" and not _is_valid_amount_canonical(c.canonical):
            merges.append(f"dropped_invalid_amount:{c.canonical}")
            amount_fts_boost.extend(["damages", "sum", "claimed"])
            continue
        valid_constraints.append(c)
    understanding.constraints = valid_constraints
    if amount_fts_boost:
        understanding.fts.must_terms = _dedupe_terms(
            understanding.fts.must_terms + amount_fts_boost
        )

    if understanding.intent in {"case_overview", "entity_matter_listing", "factual_lookup"}:
        understanding.retrieval_mode = "SIMPLE"
        merges.append(f"forced_simple:{understanding.intent}")

    if not understanding.search_passes:
        understanding.search_passes = _fallback_search_passes(
            query, understanding.intent, case_terms,
        )
        merges.append("search_passes:fallback_only")

    understanding.facet_queries = _facet_queries_from_passes(understanding.search_passes)
    if not understanding.facet_queries and understanding.intent == "case_overview":
        understanding.facet_queries = _default_facet_queries(case_terms)
        if not used_llm:
            understanding.search_passes = _passes_from_facet_queries(understanding.facet_queries)

    if not understanding.coverage_goal:
        if understanding.intent == "entity_matter_listing":
            understanding.coverage_goal = "per-document matter listing"
        elif understanding.intent == "case_overview":
            understanding.coverage_goal = "broad matter summary"
        elif understanding.intent == "factual_lookup":
            understanding.coverage_goal = "pinpoint fact"
        else:
            understanding.coverage_goal = "relevant passages"

    understanding.rule_merges = merges
    return understanding


def _apply_listing_fields(
    understanding: QueryUnderstanding,
    query: str,
    *,
    db: Session | None = None,
    workspace_id: str | None = None,
) -> QueryUnderstanding:
    if understanding.intent != "entity_matter_listing":
        return understanding
    understanding.retrieval_mode = "SIMPLE"
    entity: QueryConstraint | None = None
    if understanding.target_entity:
        entity = QueryConstraint(
            type="party",
            canonical=understanding.target_entity.canonical,
            surfaces=list(understanding.target_entity.surfaces),
        )
    for c in understanding.constraints:
        if c.type == "party" and not entity:
            entity = c
            break
    if not entity and settings.enable_regex_nlp:
        entity = _extract_listing_target_entity(query)
    v_parties = _extract_listing_v_party_constraints(query)
    if v_parties:
        seen_party = {c.canonical.casefold() for c in understanding.constraints if c.type == "party"}
        for vp in v_parties:
            if vp.canonical.casefold() not in seen_party:
                understanding.constraints.append(vp)
                seen_party.add(vp.canonical.casefold())
        if not entity:
            entity = v_parties[0]
    if not entity:
        return understanding
    resolved: list[str] = []
    party_constraints = [c for c in understanding.constraints if c.type == "party"]
    if not party_constraints:
        party_constraints = [entity]
    if db is not None and workspace_id:
        for pc in party_constraints:
            resolved.extend(
                resolve_party_canonicals(
                    db,
                    workspace_id,
                    canonical=pc.canonical,
                    surfaces=pc.surfaces,
                )
            )
    if resolved:
        seen_r: set[str] = set()
        deduped: list[str] = []
        for r in resolved:
            key = r.casefold()
            if key in seen_r:
                continue
            seen_r.add(key)
            deduped.append(r)
        resolved = deduped
    else:
        resolved = [entity.canonical]
    understanding.target_entity = TargetEntity(
        canonical=entity.canonical,
        surfaces=entity.surfaces,
        resolved_canonicals=resolved or [entity.canonical],
    )
    terms = _dedupe_terms(
        [t for t in entity.canonical.split() if len(t) > 2]
        + [t.casefold() for s in entity.surfaces for t in s.split() if len(t) > 2]
    )
    if terms:
        understanding.fts.must_terms = terms[:2]
        understanding.fts.phrases = [entity.surfaces[0]] if entity.surfaces else []
    if not understanding.search_passes:
        understanding.search_passes = _fallback_search_passes(
            query, understanding.intent, None,
        )
    return understanding


def _needs_overview_pass_expansion(passes: list[SearchPass]) -> bool:
    return len(passes) < 4


def _needs_listing_pass_expansion(passes: list[SearchPass]) -> bool:
    if len(passes) >= 3:
        return False
    if len(passes) == 1 and passes[0].label in {"entity_anchor", "anchor", "fallback"}:
        return True
    return len(passes) < 3


def _apply_overview_fields(
    understanding: QueryUnderstanding,
    query: str,
    *,
    db: Session | None = None,
    workspace_id: str | None = None,
) -> QueryUnderstanding:
    if understanding.intent != "case_overview":
        return understanding
    case_terms = _case_name_terms(query) or understanding.fts.must_terms[:2]
    understanding.retrieval_mode = "SIMPLE"
    if not understanding.overview_facets:
        understanding.overview_facets = list(DEFAULT_OVERVIEW_FACETS)
    if case_terms and not understanding.fts.must_terms:
        understanding.fts.must_terms = case_terms

    if not _case_name_terms(query):
        party: QueryConstraint | None = None
        for c in understanding.constraints:
            if c.type == "party":
                party = c
                break
        if not party:
            party = _party_from_filed_by_phrase(query)
        if not party and db is not None and workspace_id:
            party = _catalog_party_constraint(db, workspace_id, query)
        if party:
            seen = {c.canonical.casefold() for c in understanding.constraints if c.type == "party"}
            if party.canonical.casefold() not in seen:
                understanding.constraints.append(party)
            resolved: list[str] = []
            if db is not None and workspace_id:
                resolved = resolve_party_canonicals(
                    db,
                    workspace_id,
                    canonical=party.canonical,
                    surfaces=party.surfaces,
                )
            understanding.target_entity = TargetEntity(
                canonical=party.canonical,
                surfaces=party.surfaces,
                resolved_canonicals=resolved or [party.canonical],
            )
            terms = _dedupe_terms(
                [t for t in party.canonical.split() if len(t) > 2]
                + [t.casefold() for s in party.surfaces for t in s.split() if len(t) > 2]
            )
            if terms:
                understanding.fts.must_terms = terms[:3]
                if party.surfaces:
                    understanding.fts.phrases = [party.surfaces[0]]
                anchor_terms = terms[:2]
                understanding.search_passes = [
                    SearchPass(
                        label="party_anchor",
                        fts_terms=anchor_terms,
                        operator="AND" if len(anchor_terms) >= 2 else "OR",
                        pin_best=True,
                    ),
                    *[
                        sp
                        for sp in understanding.search_passes
                        if sp.label not in {"party_anchor", "entity_anchor"}
                    ],
                ]

    return understanding


def _extract_rule_constraints(query: str) -> list[QueryConstraint]:
    if not settings.enable_regex_nlp:
        return []
    from app.services.entity_index import (
        AMOUNT_PATTERN,
        CONDITION_PATTERN,
        COURT_PATTERN,
        DATE_PATTERN,
        IDENTIFIER_PATTERN,
        LEGAL_ACTOR_PATTERN,
        ORG_PARTY_PATTERN,
        PARTY_PATTERN,
        normalize_condition,
        normalize_date,
        normalize_legal_actor,
    )

    constraints: list[QueryConstraint] = []
    seen: set[tuple[str, str]] = set()

    for m in DATE_PATTERN.finditer(query):
        surface = m.group(0)
        canonical = normalize_date(surface)
        if canonical and ("date", canonical) not in seen:
            seen.add(("date", canonical))
            constraints.append(QueryConstraint(type="date", canonical=canonical, surfaces=[surface]))

    for m in CONDITION_PATTERN.finditer(query):
        surface = m.group(0)
        canonical = normalize_condition(surface)
        if ("condition", canonical) not in seen:
            seen.add(("condition", canonical))
            constraints.append(QueryConstraint(type="condition", canonical=canonical, surfaces=[surface]))

    for m in PARTY_PATTERN.finditer(query):
        surface = m.group(0)
        canonical = normalize_party(surface)
        if ("party", canonical) not in seen:
            seen.add(("party", canonical))
            constraints.append(QueryConstraint(type="party", canonical=canonical, surfaces=[surface]))

    for m in ORG_PARTY_PATTERN.finditer(query):
        surface = m.group(0).strip()
        canonical = normalize_party(surface)
        if ("party", canonical) not in seen:
            seen.add(("party", canonical))
            constraints.append(QueryConstraint(type="party", canonical=canonical, surfaces=[surface]))

    listing_entity = _extract_listing_target_entity(query)
    if listing_entity and ("party", listing_entity.canonical) not in seen:
        seen.add(("party", listing_entity.canonical))
        constraints.append(listing_entity)

    for m in IDENTIFIER_PATTERN.finditer(query):
        surface = m.group(0)
        canonical = surface.strip().casefold()
        if not re.search(r"\d", canonical):
            continue
        if ("identifier", canonical) not in seen:
            seen.add(("identifier", canonical))
            constraints.append(QueryConstraint(type="identifier", canonical=canonical, surfaces=[surface]))

    for m in AMOUNT_PATTERN.finditer(query):
        surface = m.group(0)
        canonical = normalize_amount(surface)
        if ("amount", canonical) not in seen:
            seen.add(("amount", canonical))
            constraints.append(QueryConstraint(type="amount", canonical=canonical, surfaces=[surface]))

    for m in LEGAL_ACTOR_PATTERN.finditer(query):
        surface = m.group(0)
        canonical = normalize_legal_actor(surface)
        if ("party", canonical) not in seen:
            seen.add(("party", canonical))
            constraints.append(QueryConstraint(type="party", canonical=canonical, surfaces=[surface]))

    for m in COURT_PATTERN.finditer(query):
        surface = m.group(0)
        canonical = normalize_party(surface)
        if ("party", canonical) not in seen:
            seen.add(("party", canonical))
            constraints.append(QueryConstraint(type="party", canonical=canonical, surfaces=[surface]))

    title_case = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,4}\b")
    for m in title_case.finditer(query):
        surface = m.group(0)
        if surface.lower() in {"party a", "party b"}:
            continue
        canonical = normalize_party(surface)
        if len(surface.split()) >= 2 and ("party", canonical) not in seen:
            seen.add(("party", canonical))
            constraints.append(QueryConstraint(type="party", canonical=canonical, surfaces=[surface]))

    return constraints


def _extract_tokens(query: str) -> list[str]:
    q = re.sub(r"(?<=\d),(?=\d)", "", query)
    q = re.sub(r'[*?:\()"\'\\]', " ", q.replace('"', " "))
    tokens = re.findall(r"[\w£$]+", q, re.UNICODE)
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        key = t.casefold()
        if key in seen or key in _STOPWORDS or len(t) <= 1:
            continue
        if t.startswith("£") or (t.isdigit() and len(t) >= 3):
            continue
        seen.add(key)
        out.append(t.casefold())
    return out


def _rule_confidence(constraints: list[QueryConstraint], query: str) -> float:
    if not constraints:
        return 0.3
    score = 0.5 + 0.15 * len(constraints)
    if not settings.enable_regex_nlp:
        return min(score, 1.0)
    from app.services.entity_index import (
        AMOUNT_PATTERN,
        CONDITION_PATTERN,
        DATE_PATTERN,
        LEGAL_ACTOR_PATTERN,
        PARTY_PATTERN,
    )

    if DATE_PATTERN.search(query) or CONDITION_PATTERN.search(query):
        score += 0.2
    if PARTY_PATTERN.search(query) or LEGAL_ACTOR_PATTERN.search(query):
        score += 0.15
    if AMOUNT_PATTERN.search(query):
        score += 0.15
    return min(score, 1.0)


def _resolve_mode(
    constraints: list[QueryConstraint],
    intent: Intent,
    *,
    llm_mode: RetrievalMode | None = None,
    force: str | None = None,
) -> RetrievalMode:
    if force == "simple":
        return "SIMPLE"
    if force == "multi_constraint":
        return "MULTI_CONSTRAINT"
    if intent in {"case_overview", "entity_matter_listing", "factual_lookup"}:
        return "SIMPLE"
    if llm_mode == "MULTI_CONSTRAINT":
        multi_intents = {"case_context", "timeline", "obligations"}
        typed = {c.type for c in constraints}
        if len(constraints) >= 2 and intent in multi_intents and len(typed) >= 2:
            return "MULTI_CONSTRAINT"
    multi_intents = {"case_context", "timeline", "obligations"}
    typed = {c.type for c in constraints}
    if len(constraints) >= 2 and intent in multi_intents and len(typed) >= 2:
        return "MULTI_CONSTRAINT"
    return "SIMPLE"


def _merge_rule_constraints(
    understanding: QueryUnderstanding,
    rule_constraints: list[QueryConstraint],
) -> QueryUnderstanding:
    existing = {(c.type, c.canonical) for c in understanding.constraints}
    merges: list[str] = list(understanding.rule_merges)
    for rc in rule_constraints:
        key = (rc.type, rc.canonical)
        if key not in existing:
            understanding.constraints.append(rc)
            existing.add(key)
            merges.append(f"rule_added:{rc.type}:{rc.canonical}")
    understanding.rule_merges = merges
    return understanding


def _validate_dates(understanding: QueryUnderstanding, query: str) -> QueryUnderstanding:
    """Cross-check LLM date constraints against rule DATE_PATTERN."""
    if not settings.enable_regex_nlp:
        return understanding
    from app.services.entity_index import DATE_PATTERN, normalize_date

    rule_dates = {normalize_date(m.group(0)) for m in DATE_PATTERN.finditer(query)}
    rule_dates.discard(None)
    for c in understanding.constraints:
        if c.type == "date" and rule_dates and c.canonical not in rule_dates:
            understanding.rule_merges.append(f"date_mismatch:{c.canonical}")
    return understanding


def _sanitize_fts_terms(raw_terms: list) -> list[str]:
    """Normalize SLM FTS terms: strip punctuation, drop question-framing tokens, cap at 2."""
    stop = frozenset({
        "what", "when", "who", "where", "which", "how", "why",
        "name", "names", "search", "find", "question", "query",
        "the", "a", "an", "of", "is", "are", "was", "were", "be",
    })
    collected: list[str] = []
    for raw in raw_terms:
        text = re.sub(r"[''`]s\b", "", str(raw), flags=re.IGNORECASE)
        text = re.sub(r"[''`]", "", text)
        text = re.sub(r"[^\w\s-]", " ", text)
        for tok in text.split():
            low = tok.casefold().strip("-")
            if len(low) < 2 or low in stop:
                continue
            if low not in collected:
                collected.append(low)
            if len(collected) >= 2:
                return collected
    return collected


def _parse_search_passes(data: list) -> list[SearchPass]:
    passes: list[SearchPass] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        terms = _sanitize_fts_terms(item.get("fts_terms") or [])
        if not terms:
            continue
        passes.append(
            SearchPass(
                label=str(item.get("label") or "pass"),
                fts_terms=terms,
                operator=item.get("operator", "AND"),
                pin_best=bool(item.get("pin_best", True)),
            )
        )
    return passes


def _parse_sub_questions(data: list) -> list[SubQuestion]:
    out: list[SubQuestion] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        terms = _sanitize_fts_terms(item.get("fts_terms") or [])
        if not terms:
            continue
        out.append(
            SubQuestion(
                label=str(item.get("label") or "sub"),
                question=str(item.get("question") or item.get("label") or ""),
                fts_terms=terms,
                operator=item.get("operator", "AND"),
                pin_best=bool(item.get("pin_best", True)),
            )
        )
    return out


def _passes_from_sub_questions(sub_questions: list[SubQuestion]) -> list[SearchPass]:
    return [
        SearchPass(
            label=sq.label,
            fts_terms=sq.fts_terms[:2],
            operator=sq.operator,
            pin_best=sq.pin_best,
        )
        for sq in sub_questions
        if sq.fts_terms
    ]


def _llm_understand(query: str, document_context: DocumentContext | None = None) -> QueryUnderstanding | None:
    ctx_block = (document_context or DocumentContext()).to_prompt_block()
    raw = completion(
        messages=[{
            "role": "user",
            "content": get_prompt("query_understanding").format(
                document_context=ctx_block,
                query=query,
            ),
        }],
        role=ModelRole.SLM,
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    if not raw:
        return None
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end])
        intent_raw = str(data.get("intent") or "general")
        intent: Intent = intent_raw if intent_raw in _VALID_INTENTS else "general"
        fts_data = data.get("fts") or {}
        sub_questions = _parse_sub_questions(data.get("sub_questions") or [])
        search_passes = _parse_search_passes(data.get("search_passes") or [])
        if not search_passes and sub_questions:
            search_passes = _passes_from_sub_questions(sub_questions)
        facet_queries = data.get("facet_queries") or {}
        if not search_passes and facet_queries:
            search_passes = _passes_from_facet_queries(facet_queries)
        constraints: list[QueryConstraint] = []
        for c in data.get("constraints") or []:
            if isinstance(c, dict) and c.get("type") and c.get("canonical"):
                constraints.append(QueryConstraint(**c))
        understanding = QueryUnderstanding(
            retrieval_mode=data.get("retrieval_mode", "SIMPLE"),
            intent=intent,
            target_entity=_parse_target_entity(data.get("target_entity")),
            constraints=constraints,
            fts=FtsPlan(
                must_terms=fts_data.get("must_terms", []),
                should_terms=fts_data.get("should_terms", []),
                phrases=fts_data.get("phrases", []),
                operator=fts_data.get("operator", "AND"),
            ),
            overview_facets=data.get("overview_facets") or [],
            facet_queries=facet_queries,
            search_passes=search_passes,
            sub_questions=sub_questions,
            coverage_goal=str(data.get("coverage_goal") or ""),
            confidence=float(data.get("confidence", 0.85)),
            used_llm=True,
        )
        return understanding
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("query understanding parse failed: %s", exc)
        return None


def _case_name_terms(query: str) -> list[str] | None:
    """Extract party tokens from 'Party A v Party B' style references."""
    parts = re.split(r"\s+v\.?\s+", query, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 2:
        left = _extract_tokens(parts[0])
        right = _extract_tokens(parts[1])
        if left and right:
            # Prefer distinctive tokens (e.g. winzo, games) over framing words (list, case).
            left_keep = [
                t
                for t in left
                if t not in _QUESTION_FRAMING_WORDS and t not in _CASE_QUERY_FRAMING
            ]
            right_keep = [
                t for t in right if t not in _QUESTION_FRAMING_WORDS and t not in _CASE_QUERY_FRAMING
            ]
            party_a = (left_keep or left)[0]
            party_b = (right_keep or right)[0]
            return _dedupe_terms([party_a, party_b])
    if not settings.enable_regex_nlp:
        return None
    match = re.search(
        r"\b([A-Z][a-z]+)\s+v\.?\s+(.+?)(?:\?|$|\s+(?:negligence|damages|facts|details))",
        query,
    )
    if not match:
        match = re.search(r"\b([A-Z][a-z]+)\s+v\.?\s+(.+)", query)
    if not match:
        return None
    party_a = match.group(1).casefold()
    party_b_tokens = _extract_tokens(match.group(2))
    if not party_b_tokens:
        return [party_a]
    return _dedupe_terms([party_a, party_b_tokens[-1]])


def _dedupe_terms(tokens: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        key = t.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


_OVERVIEW_FACET_SUB_QUESTIONS: dict[str, tuple[str, list[str]]] = {
    "parties": ("Who are the parties?", ["plaintiff", "defendant", "informant"]),
    "central_facts": ("What are the central facts?", ["facts", "occurred", "alleged"]),
    "damages": ("What damages or relief was claimed?", ["damages", "relief", "penalty"]),
    "dates": ("What are key dates and procedural history?", ["date", "filed", "period"]),
    "court": ("What court or forum heard the case?", ["court", "commission", "forum"]),
    "outcome": ("What was the outcome or holding?", ["judgment", "order", "disposition"]),
}


def _overview_sub_questions_from_facets(facets: list[str] | None = None) -> list[SubQuestion]:
    """Facet-driven sub-questions for case overview (dynamic, not corpus-specific)."""
    labels = facets or DEFAULT_OVERVIEW_FACETS
    out: list[SubQuestion] = []
    for label in labels:
        spec = _OVERVIEW_FACET_SUB_QUESTIONS.get(label)
        if not spec:
            continue
        question, terms = spec
        out.append(
            SubQuestion(
                label=label,
                question=question,
                fts_terms=terms,
                pin_best=True,
            )
        )
    return out


def _compound_sub_questions_from_query(query: str) -> list[SubQuestion]:
    """Emit sub-questions for compound factual queries without regex intent classifiers."""
    q = query.casefold()
    out: list[SubQuestion] = []
    if query.count("?") < 2 and not (
        ("name" in q or "son" in q or "child" in q)
        and ("age" in q or "old" in q or "date" in q or "accident" in q)
    ):
        return out
    if "name" in q or "son" in q or "child" in q or "who" in q:
        out.append(
            SubQuestion(
                label="name",
                question="Who is the named person?",
                fts_terms=["infant", "son"],
                pin_best=True,
            )
        )
    if "age" in q or "how old" in q or "old" in q:
        out.append(
            SubQuestion(
                label="age",
                question="What is the person's age?",
                fts_terms=["aged", "years"],
                pin_best=True,
            )
        )
    if "date" in q or "accident" in q or "when" in q or "incident" in q:
        out.append(
            SubQuestion(
                label="date",
                question="When did the incident occur?",
                fts_terms=["accident", "occurred"],
                pin_best=True,
            )
        )
    if _is_factual_amount_query(query) or "damage" in q or "amount" in q or "claim" in q:
        out.append(
            SubQuestion(
                label="damages",
                question="What damages or amount was claimed?",
                fts_terms=["damages", "sum"],
                pin_best=True,
            )
        )
    return out


def _token_catalog_fallback_understanding(
    query: str,
    *,
    db: Session | None = None,
    workspace_id: str | None = None,
) -> QueryUnderstanding:
    """Deterministic fallback when SLM is unavailable — tokens + workspace party catalog."""
    constraints: list[QueryConstraint] = []
    party: QueryConstraint | None = None
    if db is not None and workspace_id:
        party = _catalog_party_constraint(db, workspace_id, query)
    if party is None and _looks_like_entity_listing_query(query):
        party = _party_from_listing_phrase(query)
    if party:
        constraints.append(party)
    intent: Intent = "general"
    if party and _looks_like_entity_listing_query(query):
        intent = "entity_matter_listing"
    case_terms = _case_name_terms(query)
    q = query.casefold()
    if intent == "general" and case_terms:
        if "case" in q and ("detail" in q or "overview" in q or "list" in q):
            intent = "case_overview"
    if intent == "general" and any(
        kw in q for kw in ("summarize", "summary", "briefing", "brief me", "what happened", "narrative")
    ):
        intent = "case_overview"
    must_terms = _dedupe_terms((case_terms or []) + _extract_tokens(query)[:2])
    search_passes = _fallback_search_passes(
        query, intent, case_terms, party_constraint=party,
    )
    facet_queries = _facet_queries_from_passes(search_passes)
    if intent == "entity_matter_listing":
        coverage_goal = "per-document matter listing"
    elif intent == "case_overview":
        coverage_goal = "broad matter summary"
    else:
        coverage_goal = "relevant passages"

    sub_questions = _compound_sub_questions_from_query(query)
    if sub_questions and intent == "general":
        intent = "factual_lookup"
        coverage_goal = "pinpoint fact"
    if sub_questions and not search_passes:
        search_passes = _passes_from_sub_questions(sub_questions)

    return QueryUnderstanding(
        retrieval_mode="SIMPLE",
        intent=intent,
        constraints=constraints,
        fts=FtsPlan(must_terms=must_terms, operator="AND"),
        facet_queries=facet_queries,
        search_passes=search_passes,
        sub_questions=sub_questions,
        coverage_goal=coverage_goal,
        confidence=0.35 if party else 0.25,
        used_llm=False,
    )


def _regex_fallback_understanding(query: str) -> QueryUnderstanding:
    constraints = _extract_rule_constraints(query)
    intent = _classify_intent(query)
    case_terms = _case_name_terms(query)
    if case_terms:
        extra = [t for t in _extract_tokens(query) if t not in case_terms]
        must_terms = _dedupe_terms(case_terms + extra[:2])
        phrases: list[str] = []
    else:
        must_terms = _extract_tokens(query)
        phrases = []
    overview_facets: list[str] = []
    listing_entity = next((c for c in constraints if c.type == "party"), None)
    search_passes = _fallback_search_passes(
        query, intent, case_terms, party_constraint=listing_entity,
    )
    facet_queries = _facet_queries_from_passes(search_passes)
    if intent == "case_overview":
        overview_facets = list(DEFAULT_OVERVIEW_FACETS)
        if not facet_queries:
            facet_queries = _default_facet_queries(case_terms)
            search_passes = _passes_from_facet_queries(facet_queries)
    if intent == "entity_matter_listing":
        coverage_goal = "per-document matter listing"
    elif intent == "case_overview":
        coverage_goal = "broad matter summary"
    elif intent == "factual_lookup":
        coverage_goal = "pinpoint fact"
    else:
        coverage_goal = "relevant passages"
    return QueryUnderstanding(
        retrieval_mode="SIMPLE",
        intent=intent,
        constraints=constraints,
        fts=FtsPlan(must_terms=must_terms, phrases=phrases, operator="AND"),
        overview_facets=overview_facets,
        facet_queries=facet_queries,
        search_passes=search_passes,
        coverage_goal=coverage_goal,
        confidence=_rule_confidence(constraints, query),
        used_llm=False,
    )


def understand_query(
    query: str,
    *,
    retrieval_mode: str = "auto",
    db: Session | None = None,
    workspace_id: str | None = None,
    document_ids: list[str] | None = None,
) -> QueryUnderstanding:
    """SLM-first query planning with document context and token+catalog fallback."""
    document_context = (
        build_document_context(db, workspace_id=workspace_id, document_ids=document_ids)
        if db is not None
        else DocumentContext(document_ids=list(document_ids or []))
    )

    understanding: QueryUnderstanding | None = None
    if settings.enable_llm_query_understanding:
        understanding = _llm_understand(query, document_context)

    if understanding is None:
        if settings.enable_regex_nlp:
            understanding = _regex_fallback_understanding(query)
        else:
            understanding = _token_catalog_fallback_understanding(
                query, db=db, workspace_id=workspace_id,
            )
    elif settings.enable_regex_nlp:
        rule_constraints = _extract_rule_constraints(query)
        understanding = _merge_rule_constraints(understanding, rule_constraints)
        understanding = _validate_dates(understanding, query)

    if not understanding.fts.must_terms and not understanding.fts.phrases:
        if understanding.intent not in {"factual_lookup", "case_overview", "entity_matter_listing"}:
            understanding.fts.must_terms = _extract_tokens(query)[:2]

    mode = _resolve_mode(
        understanding.constraints,
        understanding.intent,
        llm_mode=understanding.retrieval_mode,
        force=retrieval_mode if retrieval_mode in {"simple", "multi_constraint"} else None,
    )
    understanding.retrieval_mode = mode
    understanding = _validate_retrieval_plan(understanding, query, used_llm=understanding.used_llm)
    understanding = _apply_overview_fields(
        understanding, query, db=db, workspace_id=workspace_id,
    )
    understanding = _apply_listing_fields(
        understanding, query, db=db, workspace_id=workspace_id,
    )

    if (
        db is not None
        and workspace_id
        and understanding.search_passes
        and settings.query_planner_repair_on_zero_hits
    ):
        from app.services.query_planner_validation import (
            expand_listing_passes,
            expand_overview_passes,
            validate_search_passes,
        )

        if understanding.intent == "entity_matter_listing" and _needs_listing_pass_expansion(
            understanding.search_passes
        ):
            understanding.search_passes = expand_listing_passes(
                understanding.search_passes,
                query=query,
                document_context=document_context,
            )
        elif understanding.intent == "case_overview" and _needs_overview_pass_expansion(
            understanding.search_passes
        ):
            understanding.search_passes = expand_overview_passes(
                understanding.search_passes,
                query=query,
                document_context=document_context,
            )

        scope_ids = document_ids
        if understanding.intent == "case_overview":
            case_terms = _case_name_terms(query) or understanding.fts.must_terms[:2]
            if case_terms and db is not None and workspace_id:
                from app.services.case_scoping import resolve_case_document_ids

                scope_ids = resolve_case_document_ids(
                    db, workspace_id, case_terms, document_ids,
                ) or document_ids

        repaired, repair_log = validate_search_passes(
            db,
            understanding.search_passes,
            query=query,
            workspace_id=workspace_id,
            document_ids=scope_ids,
            document_context=document_context,
        )
        understanding.search_passes = repaired
        understanding.pass_repairs = repair_log
        understanding.facet_queries = _facet_queries_from_passes(repaired)

    if understanding.search_passes:
        if understanding.target_entity and understanding.intent == "case_overview":
            party_terms = [
                t
                for t in understanding.target_entity.canonical.split()
                if len(t) > 2
            ]
            if party_terms:
                understanding.fts.must_terms = party_terms[:3]
                understanding.fts.operator = "AND"
            else:
                understanding.fts.must_terms = list(understanding.search_passes[0].fts_terms[:2])
                understanding.fts.operator = understanding.search_passes[0].operator
        else:
            understanding.fts.must_terms = list(understanding.search_passes[0].fts_terms[:2])
            understanding.fts.operator = understanding.search_passes[0].operator

    if understanding.intent == "case_overview" and not understanding.sub_questions:
        facets = understanding.overview_facets or DEFAULT_OVERVIEW_FACETS
        understanding = understanding.model_copy(
            update={"sub_questions": _overview_sub_questions_from_facets(facets)},
        )

    return understanding


def understanding_summary(u: QueryUnderstanding) -> dict:
    summary = {
        "mode": u.retrieval_mode,
        "intent": u.intent,
        "confidence": u.confidence,
        "used_llm": u.used_llm,
        "constraint_count": len(u.constraints),
        "fts_terms": len(u.fts.must_terms) + len(u.fts.should_terms),
        "rule_merges": u.rule_merges[:5],
        "coverage_goal": u.coverage_goal,
        "search_pass_count": len(u.search_passes),
        "sub_question_count": len(u.sub_questions),
        "pass_repairs": u.pass_repairs[:5],
    }
    if u.intent == "case_overview":
        summary["overview_facets"] = u.overview_facets
        summary["facet_count"] = len(u.facet_queries)
        summary["search_pass_labels"] = [p.label for p in u.search_passes]
    if u.intent == "entity_matter_listing" and u.target_entity:
        summary["target_entity"] = u.target_entity.canonical
        summary["resolved_canonicals"] = u.target_entity.resolved_canonicals
    if u.sub_questions:
        summary["sub_question_labels"] = [sq.label for sq in u.sub_questions]
    return summary
