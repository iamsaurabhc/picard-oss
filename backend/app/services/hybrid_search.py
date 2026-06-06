from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Chunk, ChunkEmbedding, Document
from app.services.chunk_embeddings import (
    blob_to_embedding,
    embed_texts,
    l2_normalize,
)
from app.services.fts_search import FtsHit
from app.services.page_embeddings import vector_page_search
from app.services.query_embedding_cache import (
    get_cached_query_embedding,
    set_cached_query_embedding,
)

logger = logging.getLogger(__name__)


def _rrf_score(rank: int, k: int) -> float:
    return 1.0 / (k + rank)


def _should_skip_vector(pool: dict[str, FtsHit], pool_cap: int) -> bool:
    """Skip vector when FTS already has strong hits (latency guardrail)."""
    if len(pool) < pool_cap:
        return False
    scores = sorted(h.score for h in pool.values())
    if not scores:
        return False
    best = scores[0]
    return best <= settings.fts_min_score + 5


def _query_embedding(
    query: str,
    *,
    workspace_id: str,
) -> list[float] | None:
    model_id = settings.embedding_model_id
    cached = get_cached_query_embedding(query, workspace_id=workspace_id, model_id=model_id)
    if cached:
        return cached
    vecs = embed_texts([query])
    if not vecs:
        return None
    vec = l2_normalize(vecs[0])
    set_cached_query_embedding(query, vec, workspace_id=workspace_id, model_id=model_id)
    return vec


def vector_search(
    db: Session,
    *,
    query: str,
    workspace_id: str,
    document_ids: list[str] | None,
    top_k: int,
) -> list[tuple[FtsHit, float]]:
    """Return (FtsHit, similarity) for top_k chunks by embedding similarity."""
    if not settings.enable_hybrid_search or not query.strip():
        return []

    query_embedding = _query_embedding(query, workspace_id=workspace_id)
    if not query_embedding:
        return []

    from app.services.retrieval_context import get_retrieval_context

    ctx = get_retrieval_context()
    cache_key = (
        workspace_id,
        ",".join(sorted(document_ids or [])),
        query.casefold().strip(),
        str(top_k),
    )
    if cache_key in ctx.chunk_vector_search_cache:
        return list(ctx.chunk_vector_search_cache[cache_key])

    from app.services.sqlite_vec import knn_chunk_ids, sqlite_vec_available

    if sqlite_vec_available():
        knn = knn_chunk_ids(
            db,
            query_vec=query_embedding,
            workspace_id=workspace_id,
            document_ids=document_ids,
            top_k=top_k,
        )
        if knn:
            from app.services.fts_search import parse_bbox

            chunk_ids = [cid for cid, _sim in knn]
            sim_by_id = {cid: sim for cid, sim in knn}
            chunks = db.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids))).all()
            chunk_order = {cid: i for i, cid in enumerate(chunk_ids)}
            chunks.sort(key=lambda c: chunk_order.get(c.id, 999))
            result = [
                (
                    FtsHit(
                        chunk_id=c.id,
                        document_id=c.document_id,
                        page_number=c.page_number,
                        text_content=c.text_content,
                        heading_path=c.heading_path,
                        section_key=c.section_key,
                        bbox_json=c.bbox_json,
                        score=-sim_by_id.get(c.id, 0.0),
                    ),
                    sim_by_id.get(c.id, 0.0),
                )
                for c in chunks
            ]
            ctx.chunk_vector_search_cache[cache_key] = result
            return result

    stmt = (
        select(ChunkEmbedding, Chunk)
        .join(Chunk, Chunk.id == ChunkEmbedding.chunk_id)
        .join(Document, Document.id == Chunk.document_id)
        .where(Document.workspace_id == workspace_id)
    )
    if document_ids:
        stmt = stmt.where(Chunk.document_id.in_(document_ids))

    rows = db.execute(stmt).all()
    if not rows:
        return []

    scored: list[tuple[FtsHit, float]] = []
    for emb_row, chunk in rows:
        vec = blob_to_embedding(emb_row.embedding_blob, emb_row.dims)
        sim = sum(x * y for x, y in zip(query_embedding, vec))
        scored.append((
            FtsHit(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                page_number=chunk.page_number,
                text_content=chunk.text_content,
                heading_path=chunk.heading_path,
                section_key=chunk.section_key,
                bbox_json=chunk.bbox_json,
                score=-sim,
            ),
            sim,
        ))

    scored.sort(key=lambda x: x[1], reverse=True)
    result = scored[:top_k]
    ctx.chunk_vector_search_cache[cache_key] = result
    return result


def enrich_fts_pool_with_hybrid(
    db: Session,
    pool: dict[str, FtsHit],
    *,
    query: str,
    workspace_id: str,
    document_ids: list[str] | None,
    pool_cap: int,
) -> dict:
    """RRF-merge vector hits into FTS pool when hybrid enabled."""
    if not settings.enable_hybrid_search or not query.strip():
        return {"hybrid": "disabled"}

    if _should_skip_vector(pool, pool_cap):
        return {"hybrid": "skipped_strong_fts"}

    if not pool:
        vec_hits = vector_search(
            db,
            query=query,
            workspace_id=workspace_id,
            document_ids=document_ids,
            top_k=settings.hybrid_pool_k,
        )
        for hit, _sim in vec_hits:
            pool[hit.chunk_id] = hit
        return {"hybrid": "vector_fallback", "vector_hits": len(vec_hits)}

    fts_ranked = sorted(pool.values(), key=lambda h: h.score)
    fts_ranks = {h.chunk_id: i + 1 for i, h in enumerate(fts_ranked)}

    vec_hits = vector_search(
        db,
        query=query,
        workspace_id=workspace_id,
        document_ids=document_ids,
        top_k=settings.hybrid_pool_k,
    )
    vec_ranks = {h.chunk_id: i + 1 for i, (h, _) in enumerate(vec_hits)}

    all_ids = set(fts_ranks) | set(vec_ranks)
    w_fts = settings.hybrid_rrf_weight_fts
    w_vec = 1.0 - w_fts
    k = settings.hybrid_rrf_k

    fused: list[tuple[str, float, FtsHit | None]] = []
    hit_by_id = {h.chunk_id: h for h in pool.values()}
    hit_by_id.update({h.chunk_id: h for h, _ in vec_hits})

    for cid in all_ids:
        rrf = 0.0
        if cid in fts_ranks:
            rrf += w_fts * _rrf_score(fts_ranks[cid], k)
        if cid in vec_ranks:
            rrf += w_vec * _rrf_score(vec_ranks[cid], k)
        hit = hit_by_id.get(cid)
        if hit:
            fused.append((cid, rrf, hit))

    fused.sort(key=lambda x: x[1], reverse=True)
    merged_pool: dict[str, FtsHit] = {}
    for cid, _score, hit in fused[:pool_cap]:
        merged_pool[cid] = hit

    pool.clear()
    pool.update(merged_pool)

    return {
        "hybrid": "rrf",
        "fts_pool": len(fts_ranks),
        "vector_hits": len(vec_hits),
        "fused_size": len(pool),
    }


def vector_page_scores(
    db: Session,
    *,
    queries: list[str],
    workspace_id: str,
    document_ids: list[str] | None,
    top_k_per_query: int = 8,
    fts_page_scores: dict[int, float] | None = None,
) -> dict[int, float]:
    """Best embedding similarity per page — page_vectors only, never chunk scan."""
    return vector_page_search(
        db,
        queries=queries,
        workspace_id=workspace_id,
        document_ids=document_ids,
        top_k_per_query=top_k_per_query,
        fts_page_scores=fts_page_scores,
    )


def fuse_page_scores_rrf(
    fts_scores: dict[int, float],
    vector_scores: dict[int, float],
) -> dict[int, float]:
    """RRF-merge FTS and vector page scores into a single ranking signal."""
    if not fts_scores and not vector_scores:
        return {}

    fts_ranked = sorted(fts_scores.items(), key=lambda x: -x[1])
    fts_ranks = {page: i + 1 for i, (page, _) in enumerate(fts_ranked)}
    vec_ranked = sorted(vector_scores.items(), key=lambda x: -x[1])
    vec_ranks = {page: i + 1 for i, (page, _) in enumerate(vec_ranked)}

    all_pages = set(fts_ranks) | set(vec_ranks)
    w_fts = settings.hybrid_rrf_weight_fts
    w_vec = 1.0 - w_fts
    k = settings.hybrid_rrf_k

    fused: dict[int, float] = {}
    for page in all_pages:
        rrf = 0.0
        if page in fts_ranks:
            rrf += w_fts * _rrf_score(fts_ranks[page], k)
        if page in vec_ranks:
            rrf += w_vec * _rrf_score(vec_ranks[page], k)
        fused[page] = rrf
    return fused
