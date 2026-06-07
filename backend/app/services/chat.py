from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ChatMessage, ChatSession, Document
from app.db.session import utc_now_iso
from app.schemas import ChatSessionOut, ChatSessionSummary, ChatSessionUpdate, ChatStreamRequest, SearchHit, SearchRequest
from app.services.case_scoping import resolve_case_document_ids
from app.services.chat_latency import ChatLatencyTracker
from app.services.citation_kernel import (
    REFUSAL_MESSAGE,
    apply_prompt_overlays,
    build_evidence_prompt_and_map,
    rank_and_cover_hits,
    stream_corpus_evidence_step,
)
from app.services.citations import refuse_gate
from app.services.entity_listing_retrieval import entity_listing_retrieve_with_progress
from app.services.fast_retrieval import fast_retrieve_for_chat
from app.services.latency_profile import apply_latency_profile
from app.services.listing_map_reduce import (
    run_listing_map_reduce_with_progress,
    should_use_listing_map_reduce,
)
from app.services.excerpt_selector import has_amount_signal
from app.services.overview_retrieval import overview_retrieve_with_progress
from app.services.planned_retrieval import PlannedRetrievalConfig, planned_retrieve_with_progress
from app.services.retrieval_context import clear_retrieval_context, reset_retrieval_context
from app.services.query_understanding import understand_query, understanding_summary, _case_name_terms
from app.services.retrieval_depth import depth_policy_to_diagnostics, resolve_retrieval_depth
from app.services.document_context import build_document_context
from app.services.pii_proxy import (
    batch_register_for_synthesis,
    get_active_proxy,
    pii_enabled_for_chat,
    pii_request_scope,
    seed_pii_context,
)
from app.services.retrieval_progress import RetrievalProgressEmitter
from app.services.search import execute_search

_GENERIC_SESSION_TITLES = frozenset({"New chat", "Assistant"})


def _parse_document_ids_json(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def session_to_out(session: ChatSession) -> ChatSessionOut:
    return ChatSessionOut(
        id=session.id,
        workspace_id=session.workspace_id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        document_ids=_parse_document_ids_json(session.document_ids_json),
    )


def _session_has_user_message(db: Session, session_id: str) -> bool:
    messages = list_messages(db, session_id)
    return any(m.role == "user" for m in messages)


def _prune_extra_draft_sessions(db: Session, workspace_id: str) -> None:
    """Keep at most one empty (no user messages) session per workspace."""
    sessions = list(
        db.scalars(
            select(ChatSession)
            .where(ChatSession.workspace_id == workspace_id)
            .order_by(ChatSession.updated_at.desc())
        ).all()
    )
    drafts = [s for s in sessions if not _session_has_user_message(db, s.id)]
    for extra in drafts[1:]:
        db.delete(extra)
    if len(drafts) > 1:
        db.commit()


def get_or_create_draft_session(db: Session, workspace_id: str, title: str | None = None) -> ChatSession:
    _prune_extra_draft_sessions(db, workspace_id)
    sessions = list(
        db.scalars(
            select(ChatSession)
            .where(ChatSession.workspace_id == workspace_id)
            .order_by(ChatSession.updated_at.desc())
        ).all()
    )
    for session in sessions:
        if not _session_has_user_message(db, session.id):
            return session
    return create_session(db, workspace_id, title)


def create_session(db: Session, workspace_id: str, title: str | None = None) -> ChatSession:
    now = utc_now_iso()
    session = ChatSession(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        title=title or "New chat",
        created_at=now,
        updated_at=now,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session(db: Session, session_id: str) -> ChatSessionOut:
    session = db.get(ChatSession, session_id)
    if not session:
        raise ValueError("Session not found")
    return session_to_out(session)


def list_sessions(db: Session, workspace_id: str) -> list[ChatSessionSummary]:
    _prune_extra_draft_sessions(db, workspace_id)
    sessions = list(
        db.scalars(
            select(ChatSession)
            .where(ChatSession.workspace_id == workspace_id)
            .order_by(ChatSession.updated_at.desc())
        ).all()
    )
    out: list[ChatSessionSummary] = []
    for session in sessions:
        messages = list_messages(db, session.id)
        has_user = any(m.role == "user" for m in messages)
        if not has_user:
            continue
        preview: str | None = None
        for msg in reversed(messages):
            if msg.role == "user":
                text = msg.content.strip()
                preview = text[:120] + ("…" if len(text) > 120 else "")
                break
        out.append(
            ChatSessionSummary(
                id=session.id,
                title=session.title,
                created_at=session.created_at,
                updated_at=session.updated_at,
                message_count=len(messages),
                has_user_message=True,
                preview=preview,
            )
        )
    return out


def update_session(db: Session, session_id: str, body: ChatSessionUpdate) -> ChatSessionOut:
    session = db.get(ChatSession, session_id)
    if not session:
        raise ValueError("Session not found")
    if body.title is not None:
        session.title = body.title
    if body.document_ids is not None:
        session.document_ids_json = json.dumps(body.document_ids)
    session.updated_at = utc_now_iso()
    db.commit()
    db.refresh(session)
    return session_to_out(session)


def delete_session(db: Session, session_id: str) -> None:
    session = db.get(ChatSession, session_id)
    if not session:
        raise ValueError("Session not found")
    db.delete(session)
    db.commit()


def _maybe_autotitle_session(session: ChatSession, user_message: str) -> None:
    title = (session.title or "").strip()
    if title.startswith("Tabular:"):
        return
    if title not in _GENERIC_SESSION_TITLES:
        return
    text = user_message.strip()
    if not text:
        return
    session.title = text[:60] + ("…" if len(text) > 60 else "")


def _touch_session_after_user_turn(db: Session, session: ChatSession, body: ChatStreamRequest) -> None:
    session.updated_at = utc_now_iso()
    if body.document_ids is not None:
        session.document_ids_json = json.dumps(body.document_ids)
    _maybe_autotitle_session(session, body.message)
    db.commit()


def list_messages(db: Session, session_id: str) -> list[ChatMessage]:
    return list(
        db.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
        ).all()
    )


def _persist_message(
    db: Session,
    *,
    session_id: str,
    role: str,
    content: str,
    references: list[dict] | None = None,
    refused: bool = False,
) -> ChatMessage:
    msg = ChatMessage(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role=role,
        content=content,
        references_json=json.dumps(references) if references else None,
        refused=1 if refused else 0,
        created_at=utc_now_iso(),
    )
    db.add(msg)
    session = db.get(ChatSession, session_id)
    if session:
        session.updated_at = utc_now_iso()
    db.commit()
    return msg


def _prompt_evidence_diagnostics(
    system_prompt: str,
    *,
    coverage_report: dict | None = None,
) -> dict:
    """Observability: verify prompt Sources contain amount/date anchors."""
    from app.services.excerpt_selector import has_explicit_monetary_amount

    prompt = system_prompt or ""
    prompt_cf = prompt.casefold()
    months = (
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    )

    def _facet_block(facet: str) -> str:
        marker = f"### evidence for: {facet}"
        if marker not in prompt_cf:
            return ""
        idx = prompt_cf.find(marker)
        rest = prompt[idx:]
        next_idx = rest.find("### evidence for:", len(marker))
        return rest[:next_idx] if next_idx > 0 else rest[:2500]

    damages = _facet_block("damages")
    dates = _facet_block("dates")
    return {
        "damages_excerpt_contains_amount": has_explicit_monetary_amount(damages or prompt),
        "dates_excerpt_contains_month": any(m in (dates or prompt_cf) for m in months),
        "facet_coverage": (coverage_report or {}).get("facet_coverage") or {},
    }


def _use_carp(body: ChatStreamRequest, understanding) -> bool:
    return (
        body.retrieval_mode == "multi_constraint"
        and settings.enable_carp
        and understanding.intent
        not in {"case_overview", "entity_matter_listing", "factual_lookup"}
    )


def get_document_names(db: Session, document_ids: list[str]) -> dict[str, str]:
    if not document_ids:
        return {}
    rows = db.scalars(select(Document).where(Document.id.in_(document_ids))).all()
    return {d.id: d.file_name for d in rows}


def _workspace_doc_names(
    db: Session,
    workspace_id: str,
    document_ids: list[str] | None,
) -> dict[str, str]:
    if document_ids:
        return get_document_names(db, document_ids)
    rows = db.scalars(select(Document).where(Document.workspace_id == workspace_id)).all()
    return {d.id: d.file_name for d in rows}


def _emit_carp_snippets(
    emitter: RetrievalProgressEmitter,
    hits: list[SearchHit],
    *,
    source: str = "carp",
) -> list[dict]:
    events: list[dict] = []
    for hit in hits:
        snippet = emitter.snippet_from_hit(hit, source)
        if not snippet:
            break
        events.append(snippet)
    return events


async def stream_chat(db: Session, body: ChatStreamRequest) -> AsyncIterator[dict]:
    reset_retrieval_context()
    latency = ChatLatencyTracker()
    with pii_request_scope(enabled=pii_enabled_for_chat(body)):
        try:
            async for ev in _stream_chat_impl(db, body, latency):
                yield ev
        finally:
            clear_retrieval_context()


async def _stream_chat_impl(
    db: Session,
    body: ChatStreamRequest,
    latency: ChatLatencyTracker,
) -> AsyncIterator[dict]:
    with apply_latency_profile(settings.chat_latency_profile) as profile_flags:
        async for ev in _stream_chat_body(db, body, latency, profile_flags):
            yield ev


async def _stream_chat_body(
    db: Session,
    body: ChatStreamRequest,
    latency: ChatLatencyTracker,
    profile_flags,
) -> AsyncIterator[dict]:
    session = db.get(ChatSession, body.session_id)
    if not session:
        raise ValueError("Session not found")

    workflow_id = body.workflow_id
    workflow_prompt: str | None = None
    persist_message = body.message
    if workflow_id:
        from app.services.workflows_store import (
            get_workflow,
            workflow_message_marker,
            workflow_prompt_prefix,
        )

        wf = get_workflow(db, workflow_id)
        workflow_prompt = workflow_prompt_prefix(wf)
        marker = workflow_message_marker(wf)
        if marker not in persist_message:
            persist_message = f"{marker}\n\n{persist_message}"

    _persist_message(db, session_id=body.session_id, role="user", content=persist_message)
    _touch_session_after_user_turn(db, session, body)

    emitter = RetrievalProgressEmitter(
        doc_names=_workspace_doc_names(db, body.workspace_id, body.document_ids)
    )

    proxy = get_active_proxy()
    if proxy is not None:
        doc_block = build_document_context(
            db,
            workspace_id=body.workspace_id,
            document_ids=body.document_ids,
        ).to_prompt_block()
        yield emitter.progress("pii", "start")
        await seed_pii_context(proxy, query=body.message, document_context_block=doc_block)
        yield emitter.progress("pii", "done")

    yield emitter.progress("understanding", "start")

    with latency.phase("understanding"):
        understanding = await asyncio.to_thread(
            understand_query,
            body.message,
            retrieval_mode=body.retrieval_mode,
            db=db,
            workspace_id=body.workspace_id,
            document_ids=body.document_ids,
        )
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
    is_overview = understanding.intent == "case_overview"
    is_listing = understanding.intent == "entity_matter_listing"

    agent_policy = None
    if body.mode == "agent":
        from app.services.agent_retrieval_policy import (
            apply_policy_to_understanding,
            build_agent_retrieval_policy,
            routing_flags_from_policy,
        )

        agent_policy = build_agent_retrieval_policy(
            body.message,
            agent_profile=settings.agent_profile,
            document_ids=body.document_ids,
            understanding=understanding,
        )
        understanding = apply_policy_to_understanding(
            understanding,
            agent_policy,
            query=body.message,
            db=db,
            workspace_id=body.workspace_id,
            document_ids=body.document_ids,
        )
        is_listing, is_overview = routing_flags_from_policy(agent_policy, understanding)

    depth_policy = resolve_retrieval_depth(
        body.message,
        understanding,
        is_overview=is_overview,
        is_listing=is_listing,
    )

    yield emitter.progress(
        "understanding",
        "done",
        intent=understanding.intent,
        mode=understanding.retrieval_mode,
        pass_count=len(understanding.search_passes),
        used_llm=understanding.used_llm,
        breadth=agent_policy.breadth if agent_policy else None,
    )

    retrieval_diagnostics: dict = {
        "understanding": understanding_summary(understanding),
        **depth_policy_to_diagnostics(depth_policy),
    }
    if agent_policy:
        retrieval_diagnostics["agent_policy"] = {
            "breadth": agent_policy.breadth,
            "profile": agent_policy.agent_profile,
            "documents_in_scope": agent_policy.documents_in_scope,
        }
    search_mode = "SIMPLE"
    bundles = None
    suggestions: list[str] = []
    refused = False
    hits: list[SearchHit] = []
    carp_refused_empty = False
    listing_map_result: dict | None = None
    citation_map = None
    system_prompt: str | None = None
    scoped_document_ids = list(body.document_ids) if body.document_ids else None
    use_fast_tier = (
        profile_flags.use_fast_tier_synthesis
        and body.mode != "agent"
        and body.retrieval_mode in ("simple", "auto")
        and not is_listing
        and not is_overview
        and depth_policy.depth_tier not in ("deep", "exhaustive")
        and not _use_carp(body, understanding)
    )
    fast_citation_map = None
    fast_system_prompt = None

    if use_fast_tier:
        with latency.phase("retrieval"):
            fast_hits, fast_citation_map, fast_system_prompt, fast_diag = await asyncio.to_thread(
                fast_retrieve_for_chat,
                db,
                query=body.message,
                understanding=understanding,
                workspace_id=body.workspace_id,
                document_ids=body.document_ids,
            )
        if fast_hits and fast_citation_map and fast_system_prompt:
            retrieval_diagnostics["fast_tier"] = fast_diag
            retrieval_diagnostics["retrieval_phase"] = "fast"
            hits = fast_hits
            top_k = len(fast_hits)
            rank_mode = "precision"
            refused = False
            search_mode = "FAST"
            yield emitter.progress("search", "done", strategy="fast_tier", hit_count=len(hits))
        else:
            use_fast_tier = False

    if is_overview and not use_fast_tier:
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
                retrieval_diagnostics["case_document_scope"] = resolved

    if not use_fast_tier and _use_carp(body, understanding):
        pool_k = body.top_k if body.top_k > settings.chat_top_k else settings.chat_retrieval_pool_k
        search_body = SearchRequest(
            query=body.message,
            workspace_id=body.workspace_id,
            document_ids=body.document_ids,
            retrieval_mode=body.retrieval_mode,
            allow_partial_disclosure=body.allow_partial_disclosure,
            top_k=pool_k,
        )
        constraint_count = len(understanding.constraints)
        yield emitter.progress(
            "search",
            "start",
            strategy="carp",
            constraint_count=constraint_count,
        )
        search_result = await asyncio.to_thread(
            execute_search,
            db,
            search_body,
            understanding,
            settings.chat_max_chunks_per_doc,
        )
        hits = search_result.hits
        top_k = settings.chat_top_k
        rank_mode = "precision"
        search_mode = search_result.mode
        bundles = search_result.bundles
        refused = search_result.refused
        carp_refused_empty = refused and len(hits) == 0
        suggestions = search_result.suggestions or []
        retrieval_diagnostics.update(search_result.retrieval_diagnostics or {})
        carp_diag = search_result.retrieval_diagnostics or {}
        yield emitter.progress(
            "search",
            "done",
            label="carp_intersection",
            intersection_pages=carp_diag.get("intersection_pages"),
            mode=search_mode,
        )
        for ev in _emit_carp_snippets(emitter, hits):
            yield ev
        yield emitter.progress("search", "done", strategy="carp", hit_count=len(hits))
    elif not use_fast_tier and is_listing:
        listing_discovery_limit = (
            agent_policy.discovery_limit if agent_policy else None
        )
        gen = entity_listing_retrieve_with_progress(
            db,
            understanding,
            workspace_id=body.workspace_id,
            document_ids=body.document_ids,
            query=body.message,
            tabular_review_id=body.tabular_review_id,
            emitter=emitter,
            discovery_doc_limit=listing_discovery_limit,
            agent_deep=body.mode == "agent",
        )
        while True:
            try:
                yield next(gen)
            except StopIteration as exc:
                hits, listing_diag = exc.value
                break
        retrieval_diagnostics.update(listing_diag)
        discovered = listing_diag.get("document_ids_discovered") or []
        if should_use_listing_map_reduce(
            discovered,
            tabular_review_id=body.tabular_review_id,
            db=db,
            document_ids=body.document_ids,
        ):
            map_gen = run_listing_map_reduce_with_progress(
                db,
                understanding,
                workspace_id=body.workspace_id,
                document_ids=body.document_ids,
                query=body.message,
                document_ids_discovered=discovered,
                documents_total_discovered=listing_diag.get("documents_total_discovered"),
                tabular_review_id=body.tabular_review_id,
                emitter=emitter,
                agent_deep=body.mode == "agent",
                map_max_docs=agent_policy.map_max_docs if agent_policy else None,
            )
            while True:
                try:
                    yield next(map_gen)
                except StopIteration as exc:
                    listing_map_result = exc.value
                    break
            retrieval_diagnostics.update(listing_map_result.get("diagnostics") or {})
            hits = []
            refused = False
            top_k = 0
            rank_mode = "listing"
        else:
            top_k = settings.chat_listing_top_k
            rank_mode = "listing"
            refused = len(hits) == 0
    elif not use_fast_tier and is_overview:
        gen = overview_retrieve_with_progress(
            db,
            understanding,
            workspace_id=body.workspace_id,
            document_ids=scoped_document_ids,
            query=body.message,
            emitter=emitter,
        )
        while True:
            try:
                yield next(gen)
            except StopIteration as exc:
                hits, overview_diag = exc.value
                break
        retrieval_diagnostics.update(overview_diag)
        top_k = depth_policy.top_k
        rank_mode = "coverage"
        refused = len(hits) == 0
    elif not use_fast_tier:
        pool_k = body.top_k if body.top_k > settings.chat_top_k else settings.chat_retrieval_pool_k
        config = PlannedRetrievalConfig(
            pool_k=pool_k,
            max_per_page=settings.chat_max_chunks_per_doc,
            min_distinct_pages=1,
            pin_best_default=False,
            pass_top_k=max(pool_k // 2, 8),
            strategy="planned",
        )
        gen = planned_retrieve_with_progress(
            db,
            understanding,
            workspace_id=body.workspace_id,
            document_ids=body.document_ids,
            query=body.message,
            config=config,
            emitter=emitter,
        )
        while True:
            try:
                yield next(gen)
            except StopIteration as exc:
                hits, planned_diag = exc.value
                break
        retrieval_diagnostics.update(planned_diag)
        top_k = settings.chat_top_k
        rank_mode = "precision"
        refused = len(hits) == 0

    overview_page_context = (
        is_overview
        and retrieval_diagnostics.get("strategy") == "overview_page_context"
    )

    if not listing_map_result and not use_fast_tier and not carp_refused_empty and (is_overview or is_listing):
        from app.services.entity_page_chunks import (
            chunks_from_entity_mentions,
            merge_search_hits,
        )

        enrich_doc_ids: list[str]
        if is_overview:
            if overview_page_context:
                enrich_doc_ids = list(
                    retrieval_diagnostics.get("scoped_document_ids")
                    or scoped_document_ids
                    or body.document_ids
                    or []
                )
            else:
                enrich_doc_ids = list(scoped_document_ids or body.document_ids or [])
        else:
            discovered = retrieval_diagnostics.get("document_ids_discovered") or []
            enrich_doc_ids = list(discovered) or sorted({h.document_id for h in hits})

        if enrich_doc_ids:
            entity_types: tuple[str, ...] = (
                ("amount", "party", "date", "identifier")
                if is_overview
                else ("party", "amount", "identifier", "date")
            )
            entity_hits = chunks_from_entity_mentions(
                db,
                body.workspace_id,
                enrich_doc_ids,
                entity_types=entity_types,
                limit=24 if is_listing else 20,
            )
            hits = merge_search_hits(hits, entity_hits)

    if not listing_map_result and not use_fast_tier and not carp_refused_empty:
        yield emitter.progress("rank", "start")
        yield emitter.progress("coverage", "start")
        if overview_page_context:
            from app.services.entity_page_chunks import dedupe_hits_by_page

            hits = dedupe_hits_by_page(hits)
        with latency.phase("rank_coverage"):
            hits, rank_cover_diag = await asyncio.to_thread(
                rank_and_cover_hits,
                db,
                query=body.message,
                understanding=understanding,
                hits=hits,
                workspace_id=body.workspace_id,
                document_ids=scoped_document_ids or body.document_ids,
                bundles=bundles,
                top_k=top_k,
                rank_mode=rank_mode,  # type: ignore[arg-type]
                page_level_pool=overview_page_context,
                depth_policy=depth_policy,
            )
        retrieval_diagnostics.update(rank_cover_diag)
        yield emitter.progress(
            "coverage",
            "done",
            ranked_count=len(hits),
            gaps_filled=rank_cover_diag.get("coverage_report", {}).get("gaps_filled", []),
        )
        yield emitter.progress("rank", "done", ranked_count=len(hits))
    elif use_fast_tier and fast_citation_map:
        yield emitter.progress("rank", "done", ranked_count=len(hits), strategy="fast_tier")
        yield emitter.progress("coverage", "done", ranked_count=len(hits), skipped=True)
    elif listing_map_result:
        cmap = listing_map_result["citation_map"]
        retrieval_diagnostics["pages_in_context"] = sorted({r.page for r in cmap.refs})
        retrieval_diagnostics["documents_in_context"] = list(
            retrieval_diagnostics.get("documents_in_answer") or []
        )
        retrieval_diagnostics["documents_missing_from_context"] = []
        yield emitter.progress("rank", "done", ranked_count=len(cmap.refs), strategy="listing_map_reduce")
        yield emitter.progress("coverage", "done", ranked_count=len(cmap.refs), skipped=True)
    elif carp_refused_empty:
        yield emitter.progress("rank", "done", ranked_count=0, skipped=True, strategy="carp_refused")
        yield emitter.progress("coverage", "done", ranked_count=0, skipped=True)

    retrieval_diagnostics["page_hits_in_context"] = len(hits)
    retrieval_diagnostics["pages_in_context"] = sorted(
        {(h.document_id, h.page_number) for h in hits}
    )

    if (refuse_gate(hits) or carp_refused_empty) and not listing_map_result:
        retrieval_diagnostics["latency_ms"] = latency.to_dict()
        yield {
            "event": "retrieval",
            "chunk_count": 0,
            "bundle_count": len(bundles or []),
            "refused": True,
            "mode": search_mode,
            "diagnostics": retrieval_diagnostics,
        }
        refs: list[dict] = []
        _persist_message(
            db,
            session_id=body.session_id,
            role="assistant",
            content=REFUSAL_MESSAGE,
            references=refs,
            refused=True,
        )
        yield {"event": "content", "delta": REFUSAL_MESSAGE}
        yield {
            "event": "references",
            "references": refs,
            "refused": True,
            "suggestions": suggestions,
        }
        yield {"event": "done"}
        return

    if is_overview:
        from app.services.entity_page_chunks import prioritize_overview_hits

        hits = prioritize_overview_hits(hits)

    tabular_overlay: str | None = None
    if use_fast_tier and fast_citation_map and fast_system_prompt:
        citation_map = fast_citation_map
        system_prompt = fast_system_prompt
    elif listing_map_result:
        citation_map = listing_map_result["citation_map"]
        system_prompt = listing_map_result["reduce_prompt"]
        if body.tabular_review_id:
            system_prompt = (
                "Structured metadata from the active tabular review was applied per document during mapping.\n\n"
                + system_prompt
            )
    else:
        doc_names = get_document_names(db, list({h.document_id for h in hits}))
        emitter.update_doc_names(doc_names)
        coverage_report = retrieval_diagnostics.get("coverage_report") or {}
        with latency.phase("prompt_build"):
            citation_map, system_prompt = await asyncio.to_thread(
                build_evidence_prompt_and_map,
                db,
                hits=hits,
                query=body.message,
                understanding=understanding,
                bundles=bundles,
                doc_names=doc_names,
                workspace_id=body.workspace_id,
                is_listing=is_listing,
                is_overview=is_overview,
                coverage_report=coverage_report,
                synthesis_mode=agent_policy.synthesis_mode if agent_policy else "chat",
                agent_profile=agent_policy.agent_profile if agent_policy else "firm",
                prompt_excerpt_cap=depth_policy.prompt_excerpt_cap,
            )
        retrieval_diagnostics["prompt_evidence"] = _prompt_evidence_diagnostics(
            system_prompt,
            coverage_report=coverage_report,
        )
        retrieval_diagnostics["coverage_report_in_prompt"] = bool(coverage_report)
        if body.tabular_review_id:
            from app.services.tabular import build_tabular_chat_context

            from app.services.citations import TABULAR_CELL_CITE_HINT

            tabular_ctx = build_tabular_chat_context(db, body.tabular_review_id)
            if tabular_ctx:
                tabular_overlay = f"{tabular_ctx}\n\n{TABULAR_CELL_CITE_HINT}"

    system_prompt = apply_prompt_overlays(
        system_prompt,
        tabular_overlay=tabular_overlay,
        workflow_prefix=workflow_prompt,
    )

    retrieval_diagnostics["citation_ref_count"] = len(citation_map.refs)
    retrieval_diagnostics["latency_ms"] = latency.to_dict()
    yield {
        "event": "retrieval",
        "chunk_count": len(citation_map.refs),
        "bundle_count": len(bundles or []),
        "refused": refused and len(citation_map.refs) == 0,
        "mode": search_mode,
        "diagnostics": retrieval_diagnostics,
    }
    yield emitter.progress(
        "context",
        "done",
        chunk_count=len(citation_map.refs),
        page_hits=len(hits),
    )

    yield emitter.progress("generate", "start")
    latency.mark_synthesis_start()

    reduce_prompt = listing_map_result.get("reduce_prompt") if listing_map_result else None
    await batch_register_for_synthesis(
        proxy,
        hits=hits,
        system_prompt=system_prompt,
        tabular_overlay=tabular_overlay,
        reduce_prompt=reduce_prompt,
    )

    async for ev in stream_corpus_evidence_step(
        db,
        body.workspace_id,
        body.message,
        hits=hits,
        intent=understanding.intent,
        bundles=bundles,
        allow_partial_disclosure=body.allow_partial_disclosure,
        search_mode=search_mode,
        skip_refuse=True,
        citation_map=citation_map,
        system_prompt=system_prompt,
    ):
        if ev["event"] == "content":
            latency.mark_first_content_token()
            yield ev
        elif ev["event"] == "final":
            validated = ev["content"]
            refs = ev["references"]
            _persist_message(
                db,
                session_id=body.session_id,
                role="assistant",
                content=validated,
                references=refs,
                refused=False,
            )
            yield {
                "event": "references",
                "references": refs,
                "content": validated,
                "citation_validation": ev["citation_validation"],
            }
            yield {"event": "done"}
