"""Page-level embedding index (mean-pooled from chunk vectors)."""

from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Chunk, Document, PageEmbedding
from app.db.session import utc_now_iso
from app.services.chunk_embeddings import (
    blob_to_embedding,
    cosine_similarity,
    embedding_to_blob,
    l2_normalize,
)
from app.services.query_embedding_cache import (
    get_cached_query_embedding,
    set_cached_query_embedding,
)

logger = logging.getLogger(__name__)


def _mean_pool(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    if len(vectors) == 1:
        return list(vectors[0])
    dims = len(vectors[0])
    out = [0.0] * dims
    for vec in vectors:
        for i, v in enumerate(vec):
            out[i] += v
    n = float(len(vectors))
    pooled = [v / n for v in out]
    return l2_normalize(pooled)


def upsert_page_embeddings_for_document(
    db: Session,
    document_id: str,
    *,
    chunk_vectors: list[tuple[str, int, list[float]]],
    workspace_id: str | None = None,
) -> int:
    """Write mean-pooled page vectors from chunk (chunk_id, page_number, vec) rows."""
    if not chunk_vectors:
        return 0
    if workspace_id is None:
        doc = db.get(Document, document_id)
        workspace_id = doc.workspace_id if doc else None
    if not workspace_id:
        return 0

    by_page: dict[int, list[list[float]]] = defaultdict(list)
    chunk_counts: dict[int, int] = defaultdict(int)
    for _cid, page, vec in chunk_vectors:
        by_page[int(page)].append(vec)
        chunk_counts[int(page)] += 1

    db.execute(delete(PageEmbedding).where(PageEmbedding.document_id == document_id))
    model_id = settings.embedding_model_id
    now = utc_now_iso()
    count = 0
    for page, vecs in by_page.items():
        pooled = _mean_pool(vecs)
        if not pooled:
            continue
        db.add(
            PageEmbedding(
                document_id=document_id,
                page_number=page,
                workspace_id=workspace_id,
                chunk_count=chunk_counts[page],
                embedding_blob=embedding_to_blob(pooled),
                model_id=model_id,
                dims=len(pooled),
                created_at=now,
            )
        )
        count += 1

    return count


def backfill_page_embeddings_from_chunks(db: Session, document_id: str) -> int:
    """Rebuild page_embeddings from chunk_embeddings BLOBs for one document."""
    from app.db.models import ChunkEmbedding

    rows = db.execute(
        select(ChunkEmbedding, Chunk.page_number)
        .join(Chunk, Chunk.id == ChunkEmbedding.chunk_id)
        .where(ChunkEmbedding.document_id == document_id)
    ).all()
    chunk_vectors: list[tuple[str, int, list[float]]] = []
    for emb, page in rows:
        vec = blob_to_embedding(emb.embedding_blob, emb.dims)
        chunk_vectors.append((emb.chunk_id, int(page), vec))
    doc = db.get(Document, document_id)
    ws = doc.workspace_id if doc else None
    return upsert_page_embeddings_for_document(
        db, document_id, chunk_vectors=chunk_vectors, workspace_id=ws,
    )


def _load_page_rows(
    db: Session,
    *,
    workspace_id: str,
    document_ids: list[str] | None,
) -> list[tuple[int, int, bytes, int]]:
    stmt = select(
        PageEmbedding.page_number,
        PageEmbedding.document_id,
        PageEmbedding.embedding_blob,
        PageEmbedding.dims,
    ).where(PageEmbedding.workspace_id == workspace_id)
    if document_ids:
        stmt = stmt.where(PageEmbedding.document_id.in_(document_ids))
    return [(int(r[0]), r[1], r[2], int(r[3])) for r in db.execute(stmt).all()]


def _should_skip_page_vector(fts_scores: dict[int, float] | None) -> bool:
    if not fts_scores:
        return False
    best = max(fts_scores.values())
    return best >= 1.0


def vector_page_search(
    db: Session,
    *,
    queries: list[str],
    workspace_id: str,
    document_ids: list[str] | None,
    top_k_per_query: int = 8,
    fts_page_scores: dict[int, float] | None = None,
) -> dict[int, float]:
    """Doc-scoped page similarity — uses page_embeddings only, never chunk scan."""
    if not settings.enable_hybrid_search:
        return {}
    if _should_skip_page_vector(fts_page_scores):
        return {}

    from app.services.chunk_embeddings import embed_texts

    model_id = settings.embedding_model_id
    query_vecs: list[list[float]] = []
    for raw in queries:
        q = (raw or "").strip()
        if not q:
            continue
        cached = get_cached_query_embedding(q, workspace_id=workspace_id, model_id=model_id)
        if cached:
            query_vecs.append(cached)
            continue
        embedded = embed_texts([q])
        if not embedded:
            continue
        vec = l2_normalize(embedded[0])
        set_cached_query_embedding(q, vec, workspace_id=workspace_id, model_id=model_id)
        query_vecs.append(vec)
    if not query_vecs:
        return {}

    from app.services.retrieval_context import get_retrieval_context

    ctx = get_retrieval_context()
    cache_key = (
        ",".join(sorted(document_ids or [])),
        str(len(query_vecs)),
        queries[0][:80] if queries else "",
    )
    if cache_key in ctx.page_vector_scores_cache:
        return dict(ctx.page_vector_scores_cache[cache_key])

    from app.services.sqlite_vec import knn_page_scores, sqlite_vec_available

    page_scores: dict[int, float] = {}
    if sqlite_vec_available() and document_ids:
        for doc_id in document_ids:
            for qv in query_vecs:
                knn = knn_page_scores(
                    db,
                    query_vec=qv,
                    document_id=doc_id,
                    top_k=top_k_per_query,
                )
                for page, sim in knn.items():
                    page_scores[page] = max(page_scores.get(page, 0.0), sim)
    else:
        rows = _load_page_rows(db, workspace_id=workspace_id, document_ids=document_ids)
        for page, _doc_id, blob, dims in rows:
            vec = blob_to_embedding(blob, dims)
            best = 0.0
            for qv in query_vecs:
                best = max(best, cosine_similarity(qv, vec))
            page_scores[page] = max(page_scores.get(page, 0.0), best)

    if top_k_per_query and len(page_scores) > top_k_per_query * max(1, len(document_ids or [1])):
        ranked = sorted(page_scores.items(), key=lambda x: -x[1])[
            : top_k_per_query * max(1, len(document_ids or [1]))
        ]
        page_scores = dict(ranked)

    ctx.page_vector_scores_cache[cache_key] = page_scores
    return page_scores
