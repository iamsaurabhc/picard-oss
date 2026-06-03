from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Chunk, ChunkEmbedding, Document
from app.services.chunk_embeddings import blob_to_embedding, cosine_similarity, embed_texts
from app.services.fts_search import FtsHit, fts_search

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


def vector_search(
    db: Session,
    *,
    query: str,
    workspace_id: str,
    document_ids: list[str] | None,
    top_k: int,
) -> list[tuple[FtsHit, float]]:
    """Return (FtsHit, similarity) for top_k chunks by embedding similarity."""
    q_vec = embed_texts([query])
    if not q_vec:
        return []

    query_embedding = q_vec[0]
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
        sim = cosine_similarity(query_embedding, vec)
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
    return scored[:top_k]


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
