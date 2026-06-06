from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Document, Workspace
from app.schemas import ContextBundleOut, SearchHit, SearchRequest, SearchResponse
from app.services.carp import filter_documents_by_metadata, run_carp
from app.services.constraint_planner import plan_query
from app.services.fts_query_builder import build_fts_match_string
from app.services.entity_listing_retrieval import entity_listing_retrieve
from app.services.planned_retrieval import PlannedRetrievalConfig, planned_retrieve
from app.services.query_understanding import understand_query, understanding_summary


def _validate_scope(
    db: Session,
    workspace_id: str,
    document_ids: list[str] | None,
) -> list[str] | None:
    ws = db.get(Workspace, workspace_id)
    if not ws:
        raise ValueError("Workspace not found")
    if not document_ids:
        return None
    valid = set(
        db.scalars(
            select(Document.id).where(
                Document.workspace_id == workspace_id,
                Document.id.in_(document_ids),
            )
        ).all()
    )
    invalid = set(document_ids) - valid
    if invalid:
        raise ValueError(f"Document IDs not in workspace: {sorted(invalid)}")
    return document_ids


def _hit_to_schema(hit: SearchHit) -> SearchHit:
    return hit


def _bundle_to_schema(bundle) -> ContextBundleOut:
    return ContextBundleOut(
        bundle_id=bundle.bundle_id,
        document_id=bundle.document_id,
        page_start=bundle.page_start,
        page_end=bundle.page_end,
        section_key=bundle.section_key,
        heading_path=bundle.heading_path,
        chunk_ids=bundle.chunk_ids,
        constraints_matched=bundle.constraints_matched,
        constraints_missing=bundle.constraints_missing,
        proximity_tier=bundle.proximity_tier,
        bm25_score=bundle.bm25_score,
        coherence_score=bundle.coherence_score,
        score=bundle.score,
    )


def _listing_search(
    db: Session,
    *,
    body: SearchRequest,
    filtered_docs: list[str] | None,
    understanding,
    diagnostics: dict,
) -> SearchResponse:
    hits, retrieve_diag = entity_listing_retrieve(
        db,
        understanding,
        workspace_id=body.workspace_id,
        document_ids=filtered_docs,
        query=body.query,
    )
    diag = {**diagnostics, **retrieve_diag, "retrieval_path": ["entity_matter_listing"]}
    if not hits:
        return SearchResponse(
            mode="SIMPLE",
            hits=[],
            refused=True,
            retrieval_diagnostics={**diag, "reason": "no_listing_hits"},
            suggestions=[
                "Check entity index is populated after parse.",
                "Try a different party name spelling.",
            ],
        )
    return SearchResponse(mode="SIMPLE", hits=hits, refused=False, retrieval_diagnostics=diag)


def _default_retrieval_config(body: SearchRequest, understanding) -> PlannedRetrievalConfig:
    if understanding.intent == "case_overview":
        return PlannedRetrievalConfig(
            pool_k=body.top_k,
            max_per_page=settings.chat_overview_max_chunks_per_page,
            min_distinct_pages=3,
            pin_best_default=True,
            entity_boost=True,
            early_page_bias=True,
            strategy="case_overview",
        )
    return PlannedRetrievalConfig(
        pool_k=body.top_k,
        max_per_page=settings.chat_max_chunks_per_doc,
        min_distinct_pages=1,
        pin_best_default=False,
        pass_top_k=max(body.top_k // 2, 8),
        strategy="planned",
    )


def _planned_search(
    db: Session,
    *,
    body: SearchRequest,
    filtered_docs: list[str] | None,
    understanding,
    diagnostics: dict,
    max_chunks_per_doc: int | None,
    retrieval_path: list[str],
) -> SearchResponse:
    config = _default_retrieval_config(body, understanding)
    if max_chunks_per_doc is not None:
        config.max_per_page = max_chunks_per_doc
    try:
        hits, retrieve_diag = planned_retrieve(
            db,
            understanding,
            workspace_id=body.workspace_id,
            document_ids=filtered_docs,
            query=body.query,
            config=config,
        )
    except Exception as exc:
        raise ValueError(f"Invalid search query: {exc}") from exc

    anchor_fts = retrieve_diag.get("anchor_fts") or build_fts_match_string(understanding.fts, raw_query_fallback=body.query)
    diag = {**diagnostics, **retrieve_diag, "retrieval_path": retrieval_path}
    if not hits:
        return SearchResponse(
            mode="SIMPLE",
            hits=[],
            refused=True,
            expanded_query=anchor_fts,
            retrieval_diagnostics={**diag, "reason": "no_fts_hits"},
            suggestions=["Try different keywords.", "Broaden document scope."],
        )

    if settings.enable_context_expansion and hits:
        from app.services.context_coverage import expand_context_hits, max_chunks_for_intent

        max_chunks = max_chunks_for_intent(understanding.intent, top_k=body.top_k)
        hits, expand_diag = expand_context_hits(
            db,
            hits,
            bundles=None,
            max_chunks=max_chunks,
            max_per_page=config.max_per_page,
        )
        diag = {**diag, **expand_diag}

    return SearchResponse(
        mode="SIMPLE",
        hits=hits,
        refused=False,
        expanded_query=anchor_fts,
        retrieval_diagnostics=diag,
    )


def execute_search(
    db: Session,
    body: SearchRequest,
    understanding=None,
    max_chunks_per_doc: int | None = None,
) -> SearchResponse:
    scoped_docs = _validate_scope(db, body.workspace_id, body.document_ids)
    filtered_docs = filter_documents_by_metadata(
        db, body.workspace_id, body.metadata_filters, scoped_docs
    )
    if filtered_docs is not None and len(filtered_docs) == 0:
        return SearchResponse(
            mode="SIMPLE",
            hits=[],
            refused=True,
            retrieval_diagnostics={"reason": "metadata_filter_empty"},
            suggestions=["No documents match metadata filters."],
        )

    if understanding is None:
        understanding = understand_query(
            body.query,
            retrieval_mode=body.retrieval_mode,
            db=db,
            workspace_id=body.workspace_id,
            document_ids=filtered_docs,
        )
    planner = plan_query(body.query, retrieval_mode=body.retrieval_mode, understanding=understanding)
    fts_match = build_fts_match_string(understanding.fts, raw_query_fallback=body.query)
    diagnostics: dict = {"understanding": understanding_summary(understanding), "fts_query": fts_match}

    carp_eligible = (
        planner.mode == "MULTI_CONSTRAINT"
        and settings.enable_carp
        and body.retrieval_mode != "simple"
        and understanding.intent
        not in {"case_overview", "entity_matter_listing", "factual_lookup"}
    )

    if understanding.intent == "entity_matter_listing":
        return _listing_search(
            db,
            body=body,
            filtered_docs=filtered_docs,
            understanding=understanding,
            diagnostics=diagnostics,
        )

    if carp_eligible:
        carp_result = run_carp(
            db,
            query=fts_match,
            workspace_id=body.workspace_id,
            constraints=planner.constraints,
            document_ids=filtered_docs,
            proximity_max_tier=body.proximity_max_tier,
            allow_partial_disclosure=body.allow_partial_disclosure,
        )
        if not carp_result.refused:
            from app.services.fts_search import parse_bbox

            carp_hits = [
                SearchHit(
                    chunk_id=h.chunk_id,
                    document_id=h.document_id,
                    page_number=h.page_number,
                    text_content=h.text_content,
                    heading_path=h.heading_path,
                    section_key=h.section_key,
                    bbox=parse_bbox(h.bbox_json),
                    score=h.score,
                )
                for h in carp_result.chunks
            ]
            carp_bundles = [_bundle_to_schema(b) for b in carp_result.bundles]
            carp_diag = {
                **diagnostics,
                **(carp_result.retrieval_diagnostics or {}),
                "retrieval_path": ["carp"],
            }
            if settings.enable_context_expansion and carp_hits:
                from app.services.context_coverage import expand_context_hits, max_chunks_for_intent

                max_chunks = max_chunks_for_intent(understanding.intent, top_k=body.top_k)
                carp_hits, expand_diag = expand_context_hits(
                    db,
                    carp_hits,
                    bundles=carp_bundles,
                    max_chunks=max_chunks,
                )
                carp_diag = {**carp_diag, **expand_diag}

            return SearchResponse(
                mode="MULTI_CONSTRAINT",
                hits=carp_hits,
                bundles=carp_bundles,
                refused=False,
                proximity_tier_used=carp_result.proximity_tier_used,
                retrieval_diagnostics=carp_diag,
                suggestions=carp_result.suggestions,
                expanded_query=fts_match,
            )

        fallback_diag = {
            **diagnostics,
            **(carp_result.retrieval_diagnostics or {}),
            "fallback_reason": "carp_refused",
            "carp_refused": True,
        }
        intersection_pages = int(
            (carp_result.retrieval_diagnostics or {}).get("intersection_pages") or 0
        )
        allow_partial = (
            settings.carp_allow_partial_disclosure
            if body.allow_partial_disclosure is None
            else body.allow_partial_disclosure
        )
        if intersection_pages == 0 and not allow_partial:
            return SearchResponse(
                mode="MULTI_CONSTRAINT",
                hits=[],
                bundles=[],
                refused=True,
                proximity_tier_used=carp_result.proximity_tier_used,
                retrieval_diagnostics={
                    **fallback_diag,
                    "retrieval_path": ["carp"],
                },
                suggestions=carp_result.suggestions,
                expanded_query=fts_match,
            )

        simple_result = _planned_search(
            db,
            body=body,
            filtered_docs=filtered_docs,
            understanding=understanding,
            diagnostics=fallback_diag,
            max_chunks_per_doc=max_chunks_per_doc,
            retrieval_path=["carp", "planned_fallback"],
        )
        if not simple_result.refused:
            return simple_result

        return SearchResponse(
            mode="MULTI_CONSTRAINT",
            hits=[],
            bundles=[],
            refused=True,
            proximity_tier_used=carp_result.proximity_tier_used,
            retrieval_diagnostics={
                **fallback_diag,
                "retrieval_path": ["carp", "planned_fallback"],
                "reason": "all_paths_exhausted",
            },
            suggestions=carp_result.suggestions,
        )

    return _planned_search(
        db,
        body=body,
        filtered_docs=filtered_docs,
        understanding=understanding,
        diagnostics=diagnostics,
        max_chunks_per_doc=max_chunks_per_doc,
        retrieval_path=["planned"],
    )
