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
from app.schemas import ChatStreamRequest, SearchHit, SearchRequest
from app.services.case_scoping import resolve_case_document_ids
from app.services.citation_judge import judge_citations
from app.services.citations import (
    build_citation_map,
    build_system_prompt,
    refuse_gate,
    references_for_api,
    validate_response,
)
from app.services.context_ranker import rank_context
from app.services.model_router import ModelRole, stream_completion
from app.services.entity_listing_retrieval import entity_listing_retrieve_with_progress
from app.services.excerpt_selector import has_amount_signal
from app.services.overview_retrieval import overview_retrieve_with_progress
from app.services.planned_retrieval import PlannedRetrievalConfig, planned_retrieve_with_progress
from app.services.query_understanding import understand_query, understanding_summary, _case_name_terms
from app.services.retrieval_progress import RetrievalProgressEmitter, consume_retrieval_generator
from app.services.search import execute_search

_DEBUG_LOG = "/Users/saurabhc/Desktop/ai-apps/picard-oss/.cursor/debug-755b1b.log"


def _debug_log(location: str, message: str, data: dict, hypothesis_id: str) -> None:
    # #region agent log
    try:
        import time
        with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "sessionId": "755b1b",
                        "location": location,
                        "message": message,
                        "data": data,
                        "timestamp": int(time.time() * 1000),
                        "hypothesisId": hypothesis_id,
                    }
                )
                + "\n"
            )
    except OSError:
        pass
    # #endregion


def create_session(db: Session, workspace_id: str, title: str | None = None) -> ChatSession:
    session = ChatSession(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        title=title or "New chat",
        created_at=utc_now_iso(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


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

    _persist_message(db, session_id=body.session_id, role="user", content=body.message)

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
    # #region agent log
    _debug_log(
        "chat.py:scoped_documents",
        "document scope for retrieval",
        {
            "intent": understanding.intent,
            "case_terms": _case_name_terms(body.message) or understanding.fts.must_terms[:2],
            "scoped_document_ids": scoped_document_ids,
            "requested_document_ids": body.document_ids,
        },
        "H5-scope",
    )
    # #endregion

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
            emitter=emitter,
        )
        progress_events, (hits, listing_diag) = _drain_retrieval_generator(gen)
        for ev in progress_events:
            yield ev
        retrieval_diagnostics.update(listing_diag)
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

    if is_overview or is_listing:
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
            pre_count = len(hits)
            hits = merge_search_hits(hits, entity_hits)
            # #region agent log
            _debug_log(
                "chat.py:entity_enrich",
                "entity index chunks merged pre-rank",
                {
                    "intent": understanding.intent,
                    "enrich_doc_count": len(enrich_doc_ids),
                    "entity_hits": len(entity_hits),
                    "pool_before": pre_count,
                    "pool_after": len(hits),
                    "amount_entity_chunks": sum(
                        1 for h in entity_hits if has_amount_signal(h.text_content)
                    ),
                    "search_pass_count": len(understanding.search_passes),
                    "search_pass_labels": [p.label for p in understanding.search_passes],
                },
                "H6-H7",
            )
            # #endregion

    yield emitter.progress("rank", "start")
    ranked_hits, rank_diagnostics = rank_context(
        body.message,
        understanding,
        hits,
        top_k=top_k,
        rank_mode=rank_mode,  # type: ignore[arg-type]
    )
    hits = ranked_hits
    retrieval_diagnostics.update(rank_diagnostics)
    retrieval_diagnostics["pages_in_context"] = sorted({h.page_number for h in hits})
    retrieval_diagnostics["documents_in_context"] = sorted({h.document_id for h in hits})
    # #region agent log
    pre_rank_by_doc: dict[str, int] = {}
    for h in hits:
        pre_rank_by_doc[h.document_id] = pre_rank_by_doc.get(h.document_id, 0) + 1
    _debug_log(
        "chat.py:post_rank",
        "ranked hits before citation map",
        {
            "intent": understanding.intent,
            "rank_mode": rank_mode,
            "ranked_count": len(hits),
            "distinct_docs": len({h.document_id for h in hits}),
            "pages": sorted({h.page_number for h in hits}),
            "chunks_per_doc": pre_rank_by_doc,
            "rank_diagnostics": {k: rank_diagnostics.get(k) for k in ("used_llm", "dropped_count", "distinct_documents", "rank_mode")},
        },
        "H3",
    )
    # #endregion
    if is_listing:
        discovered = retrieval_diagnostics.get("document_ids_discovered") or []
        in_ctx = retrieval_diagnostics["documents_in_context"]
        retrieval_diagnostics["documents_missing_from_context"] = [
            d for d in discovered if d not in in_ctx
        ]
    yield emitter.progress("rank", "done", ranked_count=len(hits))

    retrieval_event = {
        "event": "retrieval",
        "chunk_count": len(hits),
        "bundle_count": len(bundles or []),
        "refused": refused and len(hits) == 0,
        "mode": search_mode,
        "diagnostics": retrieval_diagnostics,
    }
    yield retrieval_event

    if refuse_gate(hits):
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

    if is_listing:
        excerpt_chars = 1200
    elif is_overview:
        excerpt_chars = 800
    elif understanding.intent == "factual_lookup":
        excerpt_chars = 600
    else:
        excerpt_chars = 400
    doc_names = get_document_names(db, list({h.document_id for h in hits}))
    emitter.update_doc_names(doc_names)
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
    )
    # #region agent log
    chunks_by_doc: dict[str, list[dict]] = {}
    for ref in citation_map.refs:
        chunks_by_doc.setdefault(ref.document_id, []).append(
            {
                "page": ref.page,
                "preview_len": len(ref.preview or ""),
                "has_amount": bool(
                    re.search(r"£|pound|\d{3,}", (ref.preview or "").casefold())
                ),
                "preview_head": (ref.preview or "")[:120],
            }
        )
    _debug_log(
        "chat.py:post_citation_map",
        "context assembled for LLM",
        {
            "intent": understanding.intent,
            "rank_mode": rank_mode,
            "top_k": top_k,
            "pool_size": len(hits),
            "excerpt_chars": excerpt_chars,
            "chunk_count": len(citation_map.refs),
            "pages_in_context": retrieval_diagnostics.get("pages_in_context"),
            "documents_in_context": len(retrieval_diagnostics.get("documents_in_context") or []),
            "documents_missing": retrieval_diagnostics.get("documents_missing_from_context"),
            "chunks_by_doc": {k: v for k, v in list(chunks_by_doc.items())[:6]},
            "system_prompt_chars": sum(len(r.preview or "") for r in citation_map.refs),
            "amount_excerpt_present": any(
                has_amount_signal(r.preview)
                and (
                    "£" in (r.preview or "")
                    or "sum of" in (r.preview or "").casefold()
                )
                for r in citation_map.refs
            ),
            "benchmark_chunk_in_ctx": any(
                r.chunk_id == "d4ae199c-81ce-4dd8-82ab-3932898a5576"
                for r in citation_map.refs
            ),
            "caption_chunks": sum(
                1 for r in citation_map.refs if r.page <= 2
            ),
        },
        "H2-H5",
    )
    # #endregion
    target_entity = (
        understanding.target_entity.canonical if understanding.target_entity else None
    )
    system_prompt = build_system_prompt(
        citation_map,
        intent=understanding.intent,
        sub_questions=understanding.sub_questions,
        target_entity=target_entity,
    )
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
    judge_result = judge_citations(validated, citation_map)
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
