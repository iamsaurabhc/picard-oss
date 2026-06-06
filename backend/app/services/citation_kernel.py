"""Shared Citation Kernel for Chat, Agent tools, and LightFlow corpus steps (Phase 7.0)."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from sqlalchemy.orm import Session

from app.config import settings
from app.schemas import ContextBundleOut, SearchHit
from app.services.citation_judge import judge_citations
from app.services.citations import (
    CitationMap,
    CitationRef,
    CitationValidation,
    MARKER_RE,
    build_citation_map,
    build_system_prompt,
    refuse_gate,
    references_for_api,
    validate_response,
)
from app.services.context_coverage import apply_context_coverage
from app.services.context_ranker import RankMode, rank_context
from app.services.model_router import ModelRole, stream_completion
from app.services.query_understanding import QueryUnderstanding

REFUSAL_MESSAGE = "No relevant information was found in the selected documents."

_MARKER_RE = MARKER_RE


@dataclass
class EvidenceStepResult:
    refused: bool
    content: str
    citation_map: CitationMap
    references: list[dict]
    validation: CitationValidation
    judge: dict | None
    diagnostics: dict = field(default_factory=dict)
    system_prompt: str | None = None


def _empty_citation_map() -> CitationMap:
    return CitationMap(refs=[], chunk_id_to_index={}, bundle_chunk_ids={})


def _empty_validation() -> CitationValidation:
    return CitationValidation(
        markers_valid=True,
        facts_stripped=0,
        markers_reassigned=0,
        cross_bundle_violation=False,
    )


def renumber_markers(text: str, offset: int) -> str:
    def _repl(m: re.Match) -> str:
        return f"[{int(m.group(1)) + offset}]"

    return _MARKER_RE.sub(_repl, text)


def merge_evidence_maps(
    steps: list[tuple[CitationMap, str | None]],
) -> tuple[CitationMap, list[str | None]]:
    """Merge per-step citation maps with global reindex; renumber optional content strings."""
    global_refs: list[CitationRef] = []
    chunk_to_index: dict[str, int] = {}
    bundle_chunk_ids: dict[str, set[str]] = {}
    renumbered_content: list[str | None] = []

    for cmap, content in steps:
        offset = len(global_refs)
        for ref in cmap.refs:
            new_index = len(global_refs) + 1
            global_refs.append(
                CitationRef(
                    index=new_index,
                    chunk_id=ref.chunk_id,
                    document_id=ref.document_id,
                    page=ref.page,
                    bbox=ref.bbox,
                    preview=ref.preview,
                    bundle_id=ref.bundle_id,
                    document_name=ref.document_name,
                    heading_path=ref.heading_path,
                    pinpoint_quote=ref.pinpoint_quote,
                )
            )
            chunk_to_index[ref.chunk_id] = new_index
        for bid, cids in cmap.bundle_chunk_ids.items():
            bundle_chunk_ids.setdefault(bid, set()).update(cids)
        if content is not None:
            renumbered_content.append(renumber_markers(content, offset))
        else:
            renumbered_content.append(None)

    merged = CitationMap(
        refs=global_refs,
        chunk_id_to_index=chunk_to_index,
        bundle_chunk_ids=bundle_chunk_ids,
    )
    return merged, renumbered_content


def enforce_cite_from_maps(content: str, allowed_maps: list[CitationMap]) -> str:
    """Strip [N] markers not present in any of the allowed upstream maps."""
    valid_indices: set[int] = set()
    for cmap in allowed_maps:
        valid_indices.update(r.index for r in cmap.refs)

    stripped = 0

    def _replace_invalid(match: re.Match) -> str:
        nonlocal stripped
        idx = int(match.group(1))
        if idx in valid_indices:
            return match.group(0)
        stripped += 1
        return ""

    return MARKER_RE.sub(_replace_invalid, content)


def build_step_context_prompt(prior_outputs: list[EvidenceStepResult]) -> str:
    """Format upstream step sources for downstream LightFlow / coordinator steps."""
    if not prior_outputs:
        return ""
    lines = [
        "Prior workflow step outputs (cite only using [N] from the merged source index below):",
        "",
    ]
    for i, step in enumerate(prior_outputs, start=1):
        lines.append(f"### Step {i}")
        if step.content and not step.refused:
            lines.append(step.content.strip())
        elif step.system_prompt:
            lines.append(step.system_prompt.strip()[:4000])
        else:
            lines.append("(no content)")
        lines.append("")
    merged, _ = merge_evidence_maps([(o.citation_map, None) for o in prior_outputs if o.citation_map.refs])
    if merged.refs:
        lines.append("Merged source index:")
        for ref in merged.refs:
            doc = ref.document_name or ref.document_id
            lines.append(f"[{ref.index}] {doc} (page {ref.page})")
    return "\n".join(lines)


def _excerpt_chars_for_intent(intent: str, *, is_listing: bool, is_overview: bool) -> int:
    if is_listing:
        return settings.chat_listing_map_excerpt_chars
    if is_overview:
        return min(settings.listing_max_chars_per_page, settings.overview_excerpt_chars)
    if intent == "factual_lookup":
        return 600
    return 400


def rank_and_cover_hits(
    db: Session,
    *,
    query: str,
    understanding: QueryUnderstanding,
    hits: list[SearchHit],
    workspace_id: str,
    document_ids: list[str] | None,
    bundles: list[ContextBundleOut] | None,
    top_k: int,
    rank_mode: RankMode,
    page_level_pool: bool = False,
) -> tuple[list[SearchHit], dict]:
    """Rank retrieval pool and apply context coverage; returns diagnostics delta."""
    diagnostics: dict = {}
    ranked_hits, rank_diagnostics = rank_context(
        query,
        understanding,
        hits,
        top_k=top_k,
        rank_mode=rank_mode,
    )
    diagnostics.update(rank_diagnostics)
    if page_level_pool:
        covered = ranked_hits[:top_k]
        if understanding.intent == "case_overview" and understanding.sub_questions:
            from app.services.context_coverage import compute_coverage_report, gap_fill_retrieval
            from app.services.entity_page_chunks import dedupe_hits_by_page, merge_search_hits

            report = compute_coverage_report(covered, understanding, rank_diagnostics=rank_diagnostics)
            needs_fill = any(v is None for v in report.sub_question_coverage.values())
            if needs_fill:
                pool = {h.chunk_id: h for h in covered}
                pool, filled = gap_fill_retrieval(
                    db,
                    query=query,
                    understanding=understanding,
                    workspace_id=workspace_id,
                    document_ids=document_ids,
                    pool=pool,
                    report=report,
                )
                if filled:
                    merged = merge_search_hits(covered, sorted(pool.values(), key=lambda h: h.score))
                    covered = dedupe_hits_by_page(merged)[:top_k]
                    diagnostics["overview_gap_fill"] = filled
        diagnostics["context_expansion_skipped"] = True
        diagnostics["page_level_pool"] = True
        diagnostics["ranked_count"] = len(covered)
        diagnostics["pages_in_context"] = sorted({h.page_number for h in covered})
        diagnostics["documents_in_context"] = sorted({h.document_id for h in covered})
        return covered, diagnostics
    covered, coverage_diag = apply_context_coverage(
        db,
        ranked_hits,
        understanding,
        query=query,
        workspace_id=workspace_id,
        document_ids=document_ids,
        bundles=bundles,
        top_k=top_k,
        rank_diagnostics=rank_diagnostics,
    )
    diagnostics.update(coverage_diag)
    diagnostics["pages_in_context"] = sorted({h.page_number for h in covered})
    diagnostics["documents_in_context"] = sorted({h.document_id for h in covered})
    if understanding.intent == "entity_matter_listing":
        discovered = diagnostics.get("document_ids_discovered") or []
        in_ctx = diagnostics["documents_in_context"]
        diagnostics["documents_missing_from_context"] = [
            d for d in discovered if d not in in_ctx
        ]
    return covered, diagnostics


def build_evidence_prompt_and_map(
    db: Session,
    *,
    hits: list[SearchHit],
    query: str,
    understanding: QueryUnderstanding,
    bundles: list[ContextBundleOut] | None,
    doc_names: dict[str, str],
    workspace_id: str,
    is_listing: bool = False,
    is_overview: bool = False,
    coverage_report: dict | None = None,
    synthesis_mode: str = "chat",
    agent_profile: str = "firm",
) -> tuple[CitationMap, str]:
    excerpt_chars = _excerpt_chars_for_intent(
        understanding.intent,
        is_listing=is_listing,
        is_overview=is_overview,
    )
    citation_map = build_citation_map(
        hits,
        bundles,
        doc_names=doc_names,
        excerpt_chars=excerpt_chars,
        question=query,
        sub_questions=understanding.sub_questions,
        prefer_amounts=is_overview,
        prefer_listing=is_listing,
        page_level=is_listing or is_overview,
        intent=understanding.intent,
        coverage_goal=understanding.coverage_goal,
        db=db,
        workspace_id=workspace_id,
    )
    target_entity = (
        understanding.target_entity.canonical if understanding.target_entity else None
    )
    coverage_report = coverage_report or {}
    system_prompt = build_system_prompt(
        citation_map,
        intent=understanding.intent,
        sub_questions=understanding.sub_questions,
        target_entity=target_entity,
        sub_question_coverage=coverage_report.get("sub_question_coverage"),
        coverage_goal=understanding.coverage_goal,
        synthesis_mode=synthesis_mode,
        agent_profile=agent_profile,
    )
    return citation_map, system_prompt


def prepare_evidence_context(
    db: Session,
    *,
    query: str,
    understanding: QueryUnderstanding,
    hits: list[SearchHit],
    workspace_id: str,
    document_ids: list[str] | None,
    bundles: list[ContextBundleOut] | None,
    doc_names: dict[str, str],
    top_k: int,
    rank_mode: RankMode,
    is_listing: bool = False,
    is_overview: bool = False,
) -> tuple[list[SearchHit], CitationMap, str, dict]:
    """Rank, cover, build citation map and system prompt."""
    covered, diagnostics = rank_and_cover_hits(
        db,
        query=query,
        understanding=understanding,
        hits=hits,
        workspace_id=workspace_id,
        document_ids=document_ids,
        bundles=bundles,
        top_k=top_k,
        rank_mode=rank_mode,
    )
    coverage_report = diagnostics.get("coverage_report") or {}
    citation_map, system_prompt = build_evidence_prompt_and_map(
        db,
        hits=covered,
        query=query,
        understanding=understanding,
        bundles=bundles,
        doc_names=doc_names,
        workspace_id=workspace_id,
        is_listing=is_listing,
        is_overview=is_overview,
        coverage_report=coverage_report,
    )
    return covered, citation_map, system_prompt, diagnostics


def apply_prompt_overlays(
    system_prompt: str,
    *,
    tabular_overlay: str | None = None,
    workflow_prefix: str | None = None,
) -> str:
    if tabular_overlay:
        system_prompt = f"{tabular_overlay}\n\n{system_prompt}"
    if workflow_prefix:
        system_prompt = f"{workflow_prefix}\n\n---\n\n{system_prompt}"
    return system_prompt


def _apply_judge_fail_closed(
    validated: str,
    judge_result: dict,
    intent: str,
) -> str:
    if (
        judge_result.get("enabled")
        and not judge_result.get("valid")
        and settings.citation_judge_fail_closed
        and intent in {"factual_lookup", "general"}
    ):
        return (
            validated
            + "\n\n_Note: Some claims could not be verified against cited sources._"
        )
    return validated


async def _synthesize_answer(
    system_prompt: str,
    query: str,
) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]
    full_answer = ""
    async for delta in stream_completion(messages=messages, role=ModelRole.LLM):
        full_answer += delta
    return full_answer


def _validate_and_judge(
    answer: str,
    citation_map: CitationMap,
    *,
    intent: str,
    search_mode: str,
    allow_partial_disclosure: bool,
) -> tuple[str, CitationValidation, dict]:
    validated, validation = validate_response(
        answer,
        citation_map,
        mode=search_mode,
        allow_partial_disclosure=allow_partial_disclosure,
        intent=intent,
    )
    judge_result = judge_citations(validated, citation_map, intent=intent)
    validated = _apply_judge_fail_closed(validated, judge_result, intent)
    return validated, validation, judge_result


async def run_corpus_evidence_step(
    db: Session,
    workspace_id: str,
    query: str,
    *,
    hits: list[SearchHit],
    intent: str = "general",
    bundles: list[ContextBundleOut] | None = None,
    synthesize: bool = True,
    allow_partial_disclosure: bool = False,
    search_mode: str = "SIMPLE",
    pre_built_map: CitationMap | None = None,
    pre_built_prompt: str | None = None,
    understanding: QueryUnderstanding | None = None,
    doc_names: dict[str, str] | None = None,
    is_listing: bool = False,
    is_overview: bool = False,
    prioritize_overview: bool = False,
    skip_refuse: bool = False,
) -> EvidenceStepResult:
    """
    Run refuse gate → map/prompt → optional synthesis → validate → judge.

    Caller supplies ranked hits or pre-built map/prompt (listing map-reduce).
    """
    diagnostics: dict = {"intent": intent, "chunk_count": len(hits)}

    if not skip_refuse and refuse_gate(hits) and pre_built_map is None:
        return EvidenceStepResult(
            refused=True,
            content=REFUSAL_MESSAGE,
            citation_map=_empty_citation_map(),
            references=[],
            validation=_empty_validation(),
            judge=None,
            diagnostics=diagnostics,
        )

    if prioritize_overview and hits:
        from app.services.entity_page_chunks import prioritize_overview_hits

        hits = prioritize_overview_hits(hits)

    if pre_built_map is not None and pre_built_prompt is not None:
        citation_map = pre_built_map
        system_prompt = pre_built_prompt
    else:
        if understanding is None or doc_names is None:
            raise ValueError("understanding and doc_names required without pre_built map")
        coverage_report: dict = {}
        citation_map, system_prompt = build_evidence_prompt_and_map(
            db,
            hits=hits,
            query=query,
            understanding=understanding,
            bundles=bundles,
            doc_names=doc_names,
            workspace_id=workspace_id,
            is_listing=is_listing,
            is_overview=is_overview,
            coverage_report=coverage_report,
        )

    if not synthesize:
        return EvidenceStepResult(
            refused=False,
            content=system_prompt,
            citation_map=citation_map,
            references=references_for_api(citation_map),
            validation=_empty_validation(),
            judge=None,
            diagnostics=diagnostics,
            system_prompt=system_prompt,
        )

    raw_answer = await _synthesize_answer(system_prompt, query)
    validated, validation, judge_result = _validate_and_judge(
        raw_answer,
        citation_map,
        intent=intent,
        search_mode=search_mode,
        allow_partial_disclosure=allow_partial_disclosure,
    )
    return EvidenceStepResult(
        refused=False,
        content=validated,
        citation_map=citation_map,
        references=references_for_api(citation_map),
        validation=validation,
        judge=judge_result,
        diagnostics=diagnostics,
        system_prompt=system_prompt,
    )


async def stream_corpus_evidence_step(
    db: Session,
    workspace_id: str,
    query: str,
    *,
    hits: list[SearchHit],
    intent: str = "general",
    bundles: list[ContextBundleOut] | None = None,
    allow_partial_disclosure: bool = False,
    search_mode: str = "SIMPLE",
    pre_built_map: CitationMap | None = None,
    pre_built_prompt: str | None = None,
    understanding: QueryUnderstanding | None = None,
    doc_names: dict[str, str] | None = None,
    is_listing: bool = False,
    is_overview: bool = False,
    prioritize_overview: bool = False,
    skip_refuse: bool = False,
    system_prompt: str | None = None,
    citation_map: CitationMap | None = None,
) -> AsyncIterator[dict]:
    """
    Stream synthesis deltas, then a final event with references and validation.

    When system_prompt and citation_map are pre-computed (chat path), pass them in
    to avoid duplicate map building.
    """
    if not skip_refuse and refuse_gate(hits) and pre_built_map is None and citation_map is None:
        yield {
            "event": "final",
            "content": REFUSAL_MESSAGE,
            "references": [],
            "refused": True,
            "citation_validation": None,
            "suggestions": None,
        }
        return

    if prioritize_overview and hits:
        from app.services.entity_page_chunks import prioritize_overview_hits

        hits = prioritize_overview_hits(hits)

    if citation_map is not None and system_prompt is not None:
        cmap = citation_map
        prompt = system_prompt
    elif pre_built_map is not None and pre_built_prompt is not None:
        cmap = pre_built_map
        prompt = pre_built_prompt
    else:
        if understanding is None or doc_names is None:
            raise ValueError("understanding and doc_names required without pre-built map")
        cmap, prompt = build_evidence_prompt_and_map(
            db,
            hits=hits,
            query=query,
            understanding=understanding,
            bundles=bundles,
            doc_names=doc_names,
            workspace_id=workspace_id,
            is_listing=is_listing,
            is_overview=is_overview,
        )

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": query},
    ]
    full_answer = ""
    async for delta in stream_completion(messages=messages, role=ModelRole.LLM):
        full_answer += delta
        yield {"event": "content", "delta": delta}

    validated, validation, judge_result = _validate_and_judge(
        full_answer,
        cmap,
        intent=intent,
        search_mode=search_mode,
        allow_partial_disclosure=allow_partial_disclosure,
    )
    yield {
        "event": "final",
        "content": validated,
        "references": references_for_api(cmap),
        "refused": False,
        "citation_validation": {
            "markers_valid": validation.markers_valid,
            "facts_stripped": validation.facts_stripped,
            "markers_reassigned": validation.markers_reassigned,
            "cross_bundle_violation": validation.cross_bundle_violation,
            "judge": judge_result,
        },
    }
