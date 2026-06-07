"""Shared chat retrieval + synthesis path for stream_chat and answer_from_corpus (UC-02)."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import settings
from app.schemas import ChatStreamRequest, SearchHit, SearchRequest
from app.services.case_scoping import resolve_case_document_ids
from app.services.citation_kernel import (
    EvidenceStepResult,
    apply_prompt_overlays,
    build_evidence_prompt_and_map,
    rank_and_cover_hits,
    run_corpus_evidence_step,
)
from app.services.citations import refuse_gate
from app.services.chat import _use_carp, get_document_names
from app.services.entity_listing_retrieval import (
    entity_listing_retrieve_with_progress,
)
from app.services.listing_map_reduce import (
    run_listing_map_reduce_with_progress,
    should_use_listing_map_reduce,
)
from app.services.retrieval_progress import RetrievalProgressEmitter, consume_retrieval_generator
from app.services.overview_retrieval import overview_retrieve
from app.services.planned_retrieval import PlannedRetrievalConfig, planned_retrieve
from app.services.agent_retrieval_policy import (
    apply_policy_to_understanding,
    build_agent_retrieval_policy,
    routing_flags_from_policy,
)
from app.services.query_understanding import understand_query, understanding_summary, _case_name_terms
from app.services.retrieval_depth import depth_policy_to_diagnostics, resolve_retrieval_depth
from app.services.search import execute_search


@dataclass
class ChatRetrievalBundle:
    hits: list[SearchHit] = field(default_factory=list)
    bundles: list | None = None
    understanding: object | None = None
    retrieval_diagnostics: dict = field(default_factory=dict)
    search_mode: str = "SIMPLE"
    refused: bool = False
    suggestions: list[str] = field(default_factory=list)
    listing_map_result: dict | None = None
    citation_map: object | None = None
    system_prompt: str | None = None
    workflow_prompt: str | None = None
    is_listing: bool = False
    is_overview: bool = False


def _resolve_workflow(db: Session, body: ChatStreamRequest) -> tuple[str | None, str | None]:
    workflow_id = body.workflow_id
    if not workflow_id:
        return None, None
    from app.services.workflows_store import get_workflow, workflow_prompt_prefix

    wf = get_workflow(db, workflow_id)
    return workflow_prompt_prefix(wf), workflow_id


def _agent_deep_retrieval(body: ChatStreamRequest, *, agent_deep: bool | None = None) -> bool:
    if agent_deep is not None:
        return agent_deep
    return body.mode == "agent"


@contextmanager
def _force_agent_rag_flags(*, catalog: bool = False):
    """Agent corpus path: query expansion; skip forced focus for catalog listing."""
    saved_q = settings.enable_query_expansion
    saved_f = settings.enable_focus_excerpts
    settings.enable_query_expansion = True
    if catalog:
        settings.enable_focus_excerpts = False
    else:
        settings.enable_focus_excerpts = True
    try:
        yield
    finally:
        settings.enable_query_expansion = saved_q
        settings.enable_focus_excerpts = saved_f


def retrieve_for_agent(db: Session, body: ChatStreamRequest, **kwargs) -> ChatRetrievalBundle:
    """Agent-mode retrieval: deeper listing/map limits and forced expansion/focus."""
    return retrieve_for_chat(db, body, agent_deep=True, **kwargs)


def retrieve_for_chat(
    db: Session,
    body: ChatStreamRequest,
    *,
    agent_deep: bool | None = None,
    on_progress: Callable[[dict], None] | None = None,
) -> ChatRetrievalBundle:
    """Deterministic retrieval shared by Chat SSE and agent answer_from_corpus."""
    agent_deep = _agent_deep_retrieval(body, agent_deep=agent_deep)
    if agent_deep:
        policy_pre = build_agent_retrieval_policy(
            body.message,
            agent_profile=settings.agent_profile,
            document_ids=body.document_ids,
        )
        rag_ctx = _force_agent_rag_flags(catalog=policy_pre.breadth == "catalog")
    else:
        rag_ctx = nullcontext()
    with rag_ctx:
        return _retrieve_for_chat_body(
            db, body, agent_deep=agent_deep, on_progress=on_progress,
        )


def _retrieve_for_chat_body(
    db: Session,
    body: ChatStreamRequest,
    *,
    agent_deep: bool,
    on_progress: Callable[[dict], None] | None,
) -> ChatRetrievalBundle:
    out = ChatRetrievalBundle()
    workflow_prompt, workflow_id = _resolve_workflow(db, body)

    if on_progress:
        on_progress({"event": "progress", "phase": "understanding", "status": "start"})

    understanding = understand_query(
        body.message,
        retrieval_mode=body.retrieval_mode,
        db=db,
        workspace_id=body.workspace_id,
        document_ids=body.document_ids,
    )
    policy = None
    if agent_deep:
        policy = build_agent_retrieval_policy(
            body.message,
            agent_profile=settings.agent_profile,
            document_ids=body.document_ids,
            understanding=understanding,
        )
        understanding = apply_policy_to_understanding(
            understanding,
            policy,
            query=body.message,
            db=db,
            workspace_id=body.workspace_id,
            document_ids=body.document_ids,
        )
        out.is_listing, out.is_overview = routing_flags_from_policy(policy, understanding)
    if workflow_id:
        from app.services.workflows_store import (
            apply_workflow_intent_hint,
            get_workflow,
            get_workflow_allowed_intents,
            get_workflow_intent_hint,
        )

        wf = get_workflow(db, workflow_id)
        understanding = apply_workflow_intent_hint(
            understanding,
            get_workflow_intent_hint(wf),
            get_workflow_allowed_intents(wf),
        )

    out.understanding = understanding
    out.workflow_prompt = workflow_prompt
    if not agent_deep:
        out.is_overview = understanding.intent == "case_overview"
        out.is_listing = understanding.intent == "entity_matter_listing"

    depth_policy = resolve_retrieval_depth(
        body.message,
        understanding,
        is_overview=out.is_overview,
        is_listing=out.is_listing,
    )
    out.retrieval_diagnostics = {
        "understanding": understanding_summary(understanding),
        **depth_policy_to_diagnostics(depth_policy),
    }
    if policy:
        out.retrieval_diagnostics["agent_policy"] = {
            "breadth": policy.breadth,
            "profile": policy.agent_profile,
            "documents_in_scope": policy.documents_in_scope,
            "intent_override": policy.intent_override,
        }

    hits: list[SearchHit] = []
    scoped_document_ids = list(body.document_ids) if body.document_ids else None

    if out.is_overview:
        case_terms = _case_name_terms(body.message) or understanding.fts.must_terms[:2]
        if case_terms:
            resolved = resolve_case_document_ids(
                db,
                body.workspace_id,
                case_terms,
                scoped_document_ids,
            )
            if resolved:
                scoped_document_ids = resolved
                out.retrieval_diagnostics["case_document_scope"] = resolved

    if _use_carp(body, understanding):
        pool_k = body.top_k if body.top_k > settings.chat_top_k else settings.chat_retrieval_pool_k
        search_body = SearchRequest(
            query=body.message,
            workspace_id=body.workspace_id,
            document_ids=body.document_ids,
            retrieval_mode=body.retrieval_mode,
            allow_partial_disclosure=body.allow_partial_disclosure,
            top_k=pool_k,
        )
        search_result = execute_search(
            db,
            search_body,
            max_chunks_per_doc=settings.chat_max_chunks_per_doc,
        )
        hits = search_result.hits
        top_k = settings.chat_top_k
        rank_mode = "precision"
        out.search_mode = search_result.mode
        out.bundles = search_result.bundles
        out.refused = search_result.refused
        out.suggestions = search_result.suggestions or []
        out.retrieval_diagnostics.update(search_result.retrieval_diagnostics or {})
    elif out.is_listing:
        discovery_limit = policy.discovery_limit if policy else (
            settings.agent_listing_discovery_doc_limit if agent_deep else None
        )
        map_max = policy.map_max_docs if policy else None
        listing_emitter = RetrievalProgressEmitter()
        listing_gen = entity_listing_retrieve_with_progress(
            db,
            understanding,
            workspace_id=body.workspace_id,
            document_ids=body.document_ids,
            query=body.message,
            tabular_review_id=body.tabular_review_id,
            emitter=listing_emitter,
            discovery_doc_limit=discovery_limit,
            agent_deep=agent_deep,
        )
        listing_events, listing_result = consume_retrieval_generator(listing_gen)
        for ev in listing_events:
            if on_progress:
                on_progress(ev)
        hits, listing_diag = listing_result
        out.retrieval_diagnostics.update(listing_diag)
        discovered = listing_diag.get("document_ids_discovered") or []
        if should_use_listing_map_reduce(
            discovered,
            tabular_review_id=body.tabular_review_id,
            db=db,
            document_ids=body.document_ids,
        ):
            map_emitter = RetrievalProgressEmitter()
            map_gen = run_listing_map_reduce_with_progress(
                db,
                understanding,
                workspace_id=body.workspace_id,
                document_ids=body.document_ids,
                query=body.message,
                document_ids_discovered=discovered,
                documents_total_discovered=listing_diag.get("documents_total_discovered"),
                tabular_review_id=body.tabular_review_id,
                emitter=map_emitter,
                agent_deep=agent_deep,
                map_max_docs=map_max,
            )
            map_events, map_result = consume_retrieval_generator(map_gen)
            for ev in map_events:
                if on_progress:
                    on_progress(ev)
            out.listing_map_result = map_result
            hits = []
            out.refused = False
            top_k = 0
            rank_mode = "listing"
        else:
            top_k = settings.agent_listing_top_k if agent_deep else settings.chat_listing_top_k
            rank_mode = "listing"
            out.refused = len(hits) == 0
    elif out.is_overview:
        hits, overview_diag = overview_retrieve(
            db,
            understanding,
            workspace_id=body.workspace_id,
            document_ids=scoped_document_ids,
            query=body.message,
        )
        out.retrieval_diagnostics.update(overview_diag)
        top_k = depth_policy.top_k
        rank_mode = "coverage"
        out.refused = len(hits) == 0
    else:
        pool_k = body.top_k if body.top_k > settings.chat_top_k else settings.chat_retrieval_pool_k
        config = PlannedRetrievalConfig(
            pool_k=pool_k,
            max_per_page=settings.chat_max_chunks_per_doc,
            min_distinct_pages=1,
            pin_best_default=False,
            pass_top_k=max(pool_k // 2, 8),
            strategy="planned",
        )
        hits, planned_diag = planned_retrieve(
            db,
            understanding,
            workspace_id=body.workspace_id,
            document_ids=body.document_ids,
            query=body.message,
            config=config,
        )
        out.retrieval_diagnostics.update(planned_diag)
        top_k = settings.chat_top_k
        rank_mode = "precision"
        out.refused = len(hits) == 0

    overview_page_context = (
        out.is_overview
        and out.retrieval_diagnostics.get("strategy") == "overview_page_context"
    )

    if not out.listing_map_result and (out.is_overview or out.is_listing):
        from app.services.entity_page_chunks import chunks_from_entity_mentions, merge_search_hits

        if out.is_overview:
            if overview_page_context:
                enrich_doc_ids = list(
                    out.retrieval_diagnostics.get("scoped_document_ids")
                    or scoped_document_ids
                    or body.document_ids
                    or []
                )
            else:
                enrich_doc_ids = list(scoped_document_ids or body.document_ids or [])
        else:
            discovered = out.retrieval_diagnostics.get("document_ids_discovered") or []
            enrich_doc_ids = list(discovered) or sorted({h.document_id for h in hits})

        if enrich_doc_ids:
            entity_types: tuple[str, ...] = (
                ("amount", "party", "date", "identifier")
                if out.is_overview
                else ("party", "amount", "identifier", "date")
            )
            entity_hits = chunks_from_entity_mentions(
                db,
                body.workspace_id,
                enrich_doc_ids,
                entity_types=entity_types,
                limit=24 if out.is_listing else 20,
            )
            hits = merge_search_hits(hits, entity_hits)

    if not out.listing_map_result:
        if overview_page_context:
            from app.services.entity_page_chunks import dedupe_hits_by_page

            hits = dedupe_hits_by_page(hits)
        hits, rank_cover_diag = rank_and_cover_hits(
            db,
            query=body.message,
            understanding=understanding,
            hits=hits,
            workspace_id=body.workspace_id,
            document_ids=scoped_document_ids or body.document_ids,
            bundles=out.bundles,
            top_k=top_k,
            rank_mode=rank_mode,  # type: ignore[arg-type]
            page_level_pool=overview_page_context,
            depth_policy=depth_policy,
        )
        out.retrieval_diagnostics.update(rank_cover_diag)
    else:
        cmap = out.listing_map_result["citation_map"]
        out.retrieval_diagnostics["pages_in_context"] = sorted({r.page for r in cmap.refs})

    out.hits = hits

    if refuse_gate(hits) and not out.listing_map_result:
        out.refused = True
        return out

    if out.is_overview:
        from app.services.entity_page_chunks import prioritize_overview_hits

        out.hits = prioritize_overview_hits(out.hits)

    tabular_overlay: str | None = None
    if out.listing_map_result:
        out.citation_map = out.listing_map_result["citation_map"]
        out.system_prompt = out.listing_map_result["reduce_prompt"]
        if body.tabular_review_id:
            out.system_prompt = (
                "Structured metadata from the active tabular review was applied per document during mapping.\n\n"
                + out.system_prompt
            )
    else:
        doc_names = get_document_names(db, list({h.document_id for h in out.hits}))
        coverage_report = out.retrieval_diagnostics.get("coverage_report") or {}
        synthesis_mode = policy.synthesis_mode if policy else ("agent" if agent_deep else "chat")
        profile = policy.agent_profile if policy else "firm"
        out.citation_map, out.system_prompt = build_evidence_prompt_and_map(
            db,
            hits=out.hits,
            query=body.message,
            understanding=understanding,
            bundles=out.bundles,
            doc_names=doc_names,
            workspace_id=body.workspace_id,
            is_listing=out.is_listing,
            is_overview=out.is_overview,
            coverage_report=coverage_report,
            synthesis_mode=synthesis_mode,
            agent_profile=profile,
            prompt_excerpt_cap=depth_policy.prompt_excerpt_cap,
        )
        if body.tabular_review_id:
            from app.services.citations import TABULAR_CELL_CITE_HINT
            from app.services.tabular import build_tabular_chat_context

            tabular_ctx = build_tabular_chat_context(db, body.tabular_review_id)
            if tabular_ctx:
                tabular_overlay = f"{tabular_ctx}\n\n{TABULAR_CELL_CITE_HINT}"

    out.system_prompt = apply_prompt_overlays(
        out.system_prompt,
        tabular_overlay=tabular_overlay,
        workflow_prefix=workflow_prompt,
    )
    return out


async def run_chat_corpus_answer(
    db: Session,
    body: ChatStreamRequest,
    *,
    on_progress: Callable[[dict], None] | None = None,
) -> EvidenceStepResult:
    """Full kernel synthesis — same path as chat post-retrieval."""
    agent_deep = _agent_deep_retrieval(body)
    bundle = retrieve_for_agent(db, body, on_progress=on_progress) if agent_deep else retrieve_for_chat(
        db, body, on_progress=on_progress,
    )
    if bundle.refused and refuse_gate(bundle.hits) and not bundle.listing_map_result:
        from app.services.citation_kernel import _empty_citation_map, _empty_validation

        return EvidenceStepResult(
            refused=True,
            content="No relevant information was found in the selected documents.",
            citation_map=_empty_citation_map(),
            references=[],
            validation=_empty_validation(),
            judge=None,
        )
    return await run_corpus_evidence_step(
        db,
        body.workspace_id,
        body.message,
        hits=bundle.hits,
        intent=bundle.understanding.intent if bundle.understanding else "general",
        bundles=bundle.bundles,
        allow_partial_disclosure=body.allow_partial_disclosure,
        search_mode=bundle.search_mode,
        skip_refuse=True,
        pre_built_map=bundle.citation_map,
        pre_built_prompt=bundle.system_prompt,
    )
