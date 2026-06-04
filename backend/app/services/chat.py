from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator, Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ChatMessage, ChatSession, Document
from app.db.session import utc_now_iso
from app.schemas import ChatSessionOut, ChatSessionSummary, ChatSessionUpdate, ChatStreamRequest, SearchHit, SearchRequest
from app.services.case_scoping import resolve_case_document_ids
from app.services.citation_judge import judge_citations
from app.services.citations import (
    build_citation_map,
    build_system_prompt,
    refuse_gate,
    references_for_api,
    validate_response,
)
from app.services.context_coverage import apply_context_coverage
from app.services.context_ranker import rank_context
from app.services.model_router import ModelRole, stream_completion
from app.services.entity_listing_retrieval import entity_listing_retrieve_with_progress
from app.services.listing_map_reduce import (
    run_listing_map_reduce_with_progress,
    should_use_listing_map_reduce,
)
from app.services.excerpt_selector import has_amount_signal
from app.services.overview_retrieval import overview_retrieve_with_progress
from app.services.planned_retrieval import PlannedRetrievalConfig, planned_retrieve_with_progress
from app.services.query_understanding import understand_query, understanding_summary, _case_name_terms
from app.services.retrieval_progress import RetrievalProgressEmitter, consume_retrieval_generator
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


def _drain_retrieval_generator(gen: Iterator[dict]) -> tuple[list[dict], tuple[list[SearchHit], dict]]:
    events, result = consume_retrieval_generator(gen)
    return events, result


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

    yield emitter.progress("understanding", "start")

    understanding = understand_query(
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

    yield emitter.progress(
        "understanding",
        "done",
        intent=understanding.intent,
        mode=understanding.retrieval_mode,
        pass_count=len(understanding.search_passes),
        used_llm=understanding.used_llm,
    )

    retrieval_diagnostics: dict = {"understanding": understanding_summary(understanding)}
    search_mode = "SIMPLE"
    bundles = None
    suggestions: list[str] = []
    refused = False
    hits: list[SearchHit] = []
    listing_map_result: dict | None = None
    scoped_document_ids = list(body.document_ids) if body.document_ids else None

    if is_overview:
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
        constraint_count = len(understanding.constraints)
        yield emitter.progress(
            "search",
            "start",
            strategy="carp",
            constraint_count=constraint_count,
        )
        search_result = execute_search(
            db,
            search_body,
            max_chunks_per_doc=settings.chat_max_chunks_per_doc,
        )
        hits = search_result.hits
        top_k = settings.chat_top_k
        rank_mode = "precision"
        search_mode = search_result.mode
        bundles = search_result.bundles
        refused = search_result.refused
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
    elif is_listing:
        gen = entity_listing_retrieve_with_progress(
            db,
            understanding,
            workspace_id=body.workspace_id,
            document_ids=body.document_ids,
            query=body.message,
            tabular_review_id=body.tabular_review_id,
            emitter=emitter,
        )
        progress_events, (hits, listing_diag) = _drain_retrieval_generator(gen)
        for ev in progress_events:
            yield ev
        retrieval_diagnostics.update(listing_diag)
        discovered = listing_diag.get("document_ids_discovered") or []
        if should_use_listing_map_reduce(
            discovered,
            tabular_review_id=body.tabular_review_id,
            db=db,
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
            )
            map_events, listing_map_result = consume_retrieval_generator(map_gen)
            for ev in map_events:
                yield ev
            retrieval_diagnostics.update(listing_map_result.get("diagnostics") or {})
            hits = []
            refused = False
            top_k = 0
            rank_mode = "listing"
        else:
            top_k = settings.chat_listing_top_k
            rank_mode = "listing"
            refused = len(hits) == 0
    elif is_overview:
        gen = overview_retrieve_with_progress(
            db,
            understanding,
            workspace_id=body.workspace_id,
            document_ids=scoped_document_ids,
            query=body.message,
            emitter=emitter,
        )
        progress_events, (hits, overview_diag) = _drain_retrieval_generator(gen)
        for ev in progress_events:
            yield ev
        retrieval_diagnostics.update(overview_diag)
        top_k = settings.chat_overview_top_k
        rank_mode = "coverage"
        refused = len(hits) == 0
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
        gen = planned_retrieve_with_progress(
            db,
            understanding,
            workspace_id=body.workspace_id,
            document_ids=body.document_ids,
            query=body.message,
            config=config,
            emitter=emitter,
        )
        progress_events, (hits, planned_diag) = _drain_retrieval_generator(gen)
        for ev in progress_events:
            yield ev
        retrieval_diagnostics.update(planned_diag)
        top_k = settings.chat_top_k
        rank_mode = "precision"
        refused = len(hits) == 0

    if not listing_map_result and (is_overview or is_listing):
        from app.services.entity_page_chunks import (
            chunks_from_entity_mentions,
            merge_search_hits,
        )

        enrich_doc_ids: list[str]
        if is_overview:
            enrich_doc_ids = list(scoped_document_ids or body.document_ids or [])
        else:
            discovered = retrieval_diagnostics.get("document_ids_discovered") or []
            enrich_doc_ids = list(discovered) or sorted({h.document_id for h in hits})

        if enrich_doc_ids:
            entity_types: tuple[str, ...] = (
                ("amount", "party", "date")
                if is_overview
                else ("party", "amount", "identifier", "date")
            )
            entity_hits = chunks_from_entity_mentions(
                db,
                body.workspace_id,
                enrich_doc_ids,
                entity_types=entity_types,
                limit=24 if is_listing else 16,
            )
            hits = merge_search_hits(hits, entity_hits)

    if not listing_map_result:
        yield emitter.progress("rank", "start")
        ranked_hits, rank_diagnostics = rank_context(
            body.message,
            understanding,
            hits,
            top_k=top_k,
            rank_mode=rank_mode,  # type: ignore[arg-type]
        )
        retrieval_diagnostics.update(rank_diagnostics)

        yield emitter.progress("coverage", "start")
        hits, coverage_diag = apply_context_coverage(
            db,
            ranked_hits,
            understanding,
            query=body.message,
            workspace_id=body.workspace_id,
            document_ids=scoped_document_ids or body.document_ids,
            bundles=bundles,
            top_k=top_k,
            rank_diagnostics=rank_diagnostics,
        )
        retrieval_diagnostics.update(coverage_diag)
        yield emitter.progress(
            "coverage",
            "done",
            chunk_count=len(hits),
            gaps_filled=coverage_diag.get("coverage_report", {}).get("gaps_filled", []),
        )
        retrieval_diagnostics["pages_in_context"] = sorted({h.page_number for h in hits})
        retrieval_diagnostics["documents_in_context"] = sorted({h.document_id for h in hits})
        if is_listing:
            discovered = retrieval_diagnostics.get("document_ids_discovered") or []
            in_ctx = retrieval_diagnostics["documents_in_context"]
            retrieval_diagnostics["documents_missing_from_context"] = [
                d for d in discovered if d not in in_ctx
            ]
        yield emitter.progress("rank", "done", ranked_count=len(hits))
    else:
        cmap = listing_map_result["citation_map"]
        retrieval_diagnostics["pages_in_context"] = sorted({r.page for r in cmap.refs})
        retrieval_diagnostics["documents_in_context"] = list(
            retrieval_diagnostics.get("documents_in_answer") or []
        )
        retrieval_diagnostics["documents_missing_from_context"] = []
        yield emitter.progress("rank", "done", ranked_count=len(cmap.refs), strategy="listing_map_reduce")
        yield emitter.progress("coverage", "done", chunk_count=len(cmap.refs), skipped=True)

    chunk_count = (
        len(listing_map_result["citation_map"].refs)
        if listing_map_result
        else len(hits)
    )
    retrieval_event = {
        "event": "retrieval",
        "chunk_count": chunk_count,
        "bundle_count": len(bundles or []),
        "refused": refused and chunk_count == 0,
        "mode": search_mode,
        "diagnostics": retrieval_diagnostics,
    }
    yield retrieval_event

    if refuse_gate(hits) and not listing_map_result:
        answer = "No relevant information was found in the selected documents."
        refs: list[dict] = []
        _persist_message(
            db,
            session_id=body.session_id,
            role="assistant",
            content=answer,
            references=refs,
            refused=True,
        )
        yield {
            "event": "content",
            "delta": answer,
        }
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

    if listing_map_result:
        citation_map = listing_map_result["citation_map"]
        system_prompt = listing_map_result["reduce_prompt"]
        coverage_report = {}
    elif is_listing:
        excerpt_chars = 1200
    elif is_overview:
        excerpt_chars = 800
    elif understanding.intent == "factual_lookup":
        excerpt_chars = 600
    else:
        excerpt_chars = 400
    if not listing_map_result:
        doc_names = get_document_names(db, list({h.document_id for h in hits}))
        emitter.update_doc_names(doc_names)
        coverage_report = retrieval_diagnostics.get("coverage_report") or {}
        citation_map = build_citation_map(
            hits,
            bundles,
            doc_names=doc_names,
            excerpt_chars=excerpt_chars,
            question=body.message,
            sub_questions=understanding.sub_questions,
            prefer_amounts=is_overview,
            prefer_listing=is_listing,
            intent=understanding.intent,
            coverage_goal=understanding.coverage_goal,
            db=db,
            workspace_id=body.workspace_id,
        )
        target_entity = (
            understanding.target_entity.canonical if understanding.target_entity else None
        )
        system_prompt = build_system_prompt(
            citation_map,
            intent=understanding.intent,
            sub_questions=understanding.sub_questions,
            target_entity=target_entity,
            sub_question_coverage=coverage_report.get("sub_question_coverage"),
            coverage_goal=understanding.coverage_goal,
        )
    if body.tabular_review_id and not listing_map_result:
        from app.services.tabular import build_tabular_chat_context

        from app.services.citations import TABULAR_CELL_CITE_HINT

        tabular_ctx = build_tabular_chat_context(db, body.tabular_review_id)
        if tabular_ctx:
            system_prompt = f"{tabular_ctx}\n\n{TABULAR_CELL_CITE_HINT}\n\n{system_prompt}"
    elif body.tabular_review_id and listing_map_result:
        system_prompt = (
            "Structured metadata from the active tabular review was applied per document during mapping.\n\n"
            + system_prompt
        )
    if workflow_prompt:
        system_prompt = f"{workflow_prompt}\n\n---\n\n{system_prompt}"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": body.message},
    ]

    yield emitter.progress("generate", "start")

    full_answer = ""
    async for delta in stream_completion(messages=messages, role=ModelRole.LLM):
        full_answer += delta
        yield {"event": "content", "delta": delta}

    validated, validation = validate_response(
        full_answer,
        citation_map,
        mode=search_mode,
        allow_partial_disclosure=body.allow_partial_disclosure,
    )
    judge_result = judge_citations(
        validated,
        citation_map,
        intent=understanding.intent,
    )
    if (
        judge_result.get("enabled")
        and not judge_result.get("valid")
        and settings.citation_judge_fail_closed
        and understanding.intent in {"factual_lookup", "general"}
    ):
        validated = (
            validated
            + "\n\n_Note: Some claims could not be verified against cited sources._"
        )
    refs = references_for_api(citation_map)
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
        "citation_validation": {
            "markers_valid": validation.markers_valid,
            "facts_stripped": validation.facts_stripped,
            "markers_reassigned": validation.markers_reassigned,
            "cross_bundle_violation": validation.cross_bundle_violation,
            "judge": judge_result,
        },
    }
    yield {"event": "done"}
