from __future__ import annotations

import json
import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.services.document_context import DocumentContext
from app.services.fts_query_builder import build_fts_match_string
from app.services.fts_search import fts_search
from app.services.model_router import ModelRole, completion
from app.services.query_understanding import DEFAULT_FACET_QUERIES, FtsPlan, SearchPass

logger = logging.getLogger(__name__)

PASS_REPAIR_PROMPT = """Some FTS search passes returned zero hits in the document index.
Suggest replacement passes using vocabulary from the document context.

Return JSON only:
{{
  "repairs": [
    {{"label": "same_label_as_failed", "fts_terms": ["term1", "term2"], "operator": "AND", "pin_best": true}}
  ]
}}

Rules:
- Each repair must use exactly 2 FTS terms drawn from document previews, parties, entities, or headings.
- Do not use question-framing words (what, when, who, name, date) as terms.
- Keep the same label as the failed pass when possible.

Document context:
{document_context}

Failed passes (zero hits):
{failed_passes}

Question: {query}"""


LISTING_PASS_EXPAND_PROMPT = """The user wants a per-document listing of legal matters involving a party.
The initial query plan has too few search passes to cover each document's parties, allegations, forum, and outcome.

Return JSON only:
{{
  "search_passes": [
    {{"label": "parties", "fts_terms": ["term1", "term2"], "operator": "AND", "pin_best": true}}
  ]
}}

Rules:
- Emit 4–6 passes with distinct labels (e.g. parties, allegations, forum, outcome, filing, relief).
- Each pass uses exactly 2 FTS terms from document context previews, parties, entities, or headings.
- Do not use question-framing words (what, when, who, list, cases) as terms.
- Preserve any existing passes that already have good labels; add missing dimensions.

Document context:
{document_context}

Existing passes:
{existing_passes}

Question: {query}"""


def expand_listing_passes(
    passes: list[SearchPass],
    *,
    query: str,
    document_context: DocumentContext | None = None,
) -> list[SearchPass]:
    """SLM expands sparse listing plans using workspace document vocabulary."""
    ctx_block = (document_context or DocumentContext()).to_prompt_block()
    existing = "\n".join(f"- {p.label}: {p.fts_terms}" for p in passes) or "(none)"
    raw = completion(
        messages=[{
            "role": "user",
            "content": LISTING_PASS_EXPAND_PROMPT.format(
                document_context=ctx_block,
                existing_passes=existing,
                query=query,
            ),
        }],
        role=ModelRole.SLM,
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    if not raw:
        return passes
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end])
        expanded: list[SearchPass] = list(passes)
        seen_labels = {p.label for p in passes}
        for item in data.get("search_passes") or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "")
            terms = [str(t) for t in (item.get("fts_terms") or [])[:2]]
            if not label or not terms or label in seen_labels:
                continue
            expanded.append(SearchPass(
                label=label,
                fts_terms=terms,
                operator=item.get("operator", "AND"),
                pin_best=bool(item.get("pin_best", True)),
            ))
            seen_labels.add(label)
        return expanded if len(expanded) > len(passes) else passes
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("listing pass expand failed: %s", exc)
        return passes


OVERVIEW_PASS_EXPAND_PROMPT = """The user wants a broad case overview (parties, facts, damages, dates, outcome).
The query plan has too few search passes to retrieve diverse evidence from the document(s).

Return JSON only:
{{
  "search_passes": [
    {{"label": "damages", "fts_terms": ["term1", "term2"], "operator": "AND", "pin_best": true}}
  ]
}}

Rules:
- Emit 5–8 passes covering parties, central facts, damages/relief, dates, court, and outcome/disposition.
- Each pass uses exactly 2 FTS terms from document context previews, parties, entities, or headings.
- Do not use question-framing words (what, when, who, details) as terms.
- Preserve existing passes; add missing dimensions.

Document context:
{document_context}

Existing passes:
{existing_passes}

Question: {query}"""


def expand_overview_passes(
    passes: list[SearchPass],
    *,
    query: str,
    document_context: DocumentContext | None = None,
) -> list[SearchPass]:
    ctx_block = (document_context or DocumentContext()).to_prompt_block()
    existing = "\n".join(f"- {p.label}: {p.fts_terms}" for p in passes) or "(none)"
    raw = completion(
        messages=[{
            "role": "user",
            "content": OVERVIEW_PASS_EXPAND_PROMPT.format(
                document_context=ctx_block,
                existing_passes=existing,
                query=query,
            ),
        }],
        role=ModelRole.SLM,
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    if not raw:
        return passes
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end])
        expanded: list[SearchPass] = list(passes)
        seen_labels = {p.label for p in passes}
        for item in data.get("search_passes") or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "")
            terms = [str(t) for t in (item.get("fts_terms") or [])[:2]]
            if not label or not terms or label in seen_labels:
                continue
            expanded.append(SearchPass(
                label=label,
                fts_terms=terms,
                operator=item.get("operator", "AND"),
                pin_best=bool(item.get("pin_best", True)),
            ))
            seen_labels.add(label)
        return expanded if len(expanded) > len(passes) else passes
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("overview pass expand failed: %s", exc)
        return passes


def probe_search_pass(
    db: Session,
    sp: SearchPass,
    *,
    workspace_id: str,
    document_ids: list[str] | None,
) -> int:
    if not sp.fts_terms:
        return 0
    plan = FtsPlan(must_terms=sp.fts_terms[:2], operator=sp.operator)
    fts_query = build_fts_match_string(plan, raw_query_fallback=" ".join(sp.fts_terms))
    if not fts_query:
        return 0
    hits = fts_search(
        db,
        query=" ".join(sp.fts_terms),
        fts_query=fts_query,
        workspace_id=workspace_id,
        document_ids=document_ids,
        top_k=1,
    )
    return len(hits)


def validate_search_passes(
    db: Session,
    passes: list[SearchPass],
    *,
    query: str,
    workspace_id: str,
    document_ids: list[str] | None,
    document_context: DocumentContext | None = None,
) -> tuple[list[SearchPass], list[str]]:
    """Probe each pass against FTS; optionally repair zero-hit passes via SLM."""
    if not passes or not workspace_id:
        return passes, []

    repairs_log: list[str] = []
    validated: list[SearchPass] = []
    failed: list[SearchPass] = []

    for sp in passes:
        hit_count = probe_search_pass(
            db, sp, workspace_id=workspace_id, document_ids=document_ids,
        )
        if hit_count > 0:
            validated.append(sp)
        else:
            failed.append(sp)
            repairs_log.append(f"zero_hits:{sp.label}:{sp.fts_terms}")

    if not failed or not settings.query_planner_repair_on_zero_hits:
        validated.extend(failed)
        return validated, repairs_log

    ctx_block = (document_context or DocumentContext()).to_prompt_block()
    failed_desc = "\n".join(
        f"- {p.label}: {p.fts_terms} ({p.operator})" for p in failed
    )
    raw = completion(
        messages=[{
            "role": "user",
            "content": PASS_REPAIR_PROMPT.format(
                document_context=ctx_block,
                failed_passes=failed_desc,
                query=query,
            ),
        }],
        role=ModelRole.SLM,
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    if not raw:
        validated.extend(failed)
        return validated, repairs_log

    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end])
        repair_by_label = {
            str(item.get("label")): SearchPass(
                label=str(item.get("label") or "repair"),
                fts_terms=[str(t) for t in (item.get("fts_terms") or [])[:2]],
                operator=item.get("operator", "AND"),
                pin_best=bool(item.get("pin_best", True)),
            )
            for item in (data.get("repairs") or [])
            if isinstance(item, dict) and item.get("fts_terms")
        }
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("pass repair parse failed: %s", exc)
        validated.extend(failed)
        return validated, repairs_log

    for sp in failed:
        repaired = repair_by_label.get(sp.label)
        if repaired and probe_search_pass(
            db, repaired, workspace_id=workspace_id, document_ids=document_ids,
        ) > 0:
            validated.append(repaired)
            repairs_log.append(f"repaired:{sp.label}:{repaired.fts_terms}")
            continue

        label_cf = sp.label.casefold()
        facet_key: str | None = None
        for fragment, key in (
            ("damage", "damages"),
            ("relief", "damages"),
            ("fact", "central_facts"),
            ("incident", "central_facts"),
            ("outcome", "outcome"),
            ("disposition", "outcome"),
            ("part", "parties"),
            ("court", "court"),
            ("date", "dates"),
            ("alleg", "central_facts"),
            ("statute", "central_facts"),
            ("filing", "central_facts"),
        ):
            if fragment in label_cf:
                facet_key = key
                break
        if facet_key and facet_key in DEFAULT_FACET_QUERIES:
            facet_terms = DEFAULT_FACET_QUERIES[facet_key][:2]
            facet_pass = SearchPass(
                label=sp.label,
                fts_terms=facet_terms,
                operator="AND",
                pin_best=True,
            )
            if probe_search_pass(
                db, facet_pass, workspace_id=workspace_id, document_ids=document_ids,
            ) > 0:
                validated.append(facet_pass)
                repairs_log.append(f"facet_repair:{sp.label}:{facet_terms}")
                continue

        if "name" in label_cf or "identity" in label_cf:
            generic = SearchPass(
                label=sp.label,
                fts_terms=["infant", "son"],
                operator="AND",
                pin_best=True,
            )
            if probe_search_pass(
                db, generic, workspace_id=workspace_id, document_ids=document_ids,
            ) > 0:
                validated.append(generic)
                repairs_log.append(f"generic_repair:{sp.label}:infant+son")
                continue

        validated.append(sp)
        repairs_log.append(f"repair_failed:{sp.label}")

    return validated, repairs_log
