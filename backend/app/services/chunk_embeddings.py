from __future__ import annotations

import logging
import math
import struct
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Chunk, ChunkEmbedding, Document
from app.db.session import utc_now_iso

logger = logging.getLogger(__name__)

_embedder = None
_embedder_failed = False

# HuggingFace name that fastembed maps to a separate ONNX repo — often leaves a broken /tmp cache.
_LEGACY_MODEL_IDS = frozenset({
    "sentence-transformers/all-MiniLM-L6-v2",
    "all-MiniLM-L6-v2",
})


def embedding_available() -> bool:
    """True when hybrid search is on and fastembed is importable."""
    if not settings.enable_hybrid_search:
        return False
    try:
        import fastembed  # noqa: F401

        return True
    except ImportError:
        return False


def _onnx_artifact_ready(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return resolved.is_file() and resolved.stat().st_size > 1024


def embedding_model_cached() -> bool:
    """True when loadable ONNX weights exist under the Picard fastembed cache."""
    cache = settings.embedding_model_cache_path
    if not cache.is_dir():
        return False
    for pattern in ("model.onnx", "model_optimized.onnx", "*.onnx"):
        for candidate in cache.rglob(pattern):
            if _onnx_artifact_ready(candidate):
                return True
    return False


def ensure_embedding_model() -> bool:
    """Download (if allowed) and load the embedding model when hybrid search is enabled."""
    if not settings.enable_hybrid_search:
        return False
    if not embedding_available():
        logger.warning(
            "ENABLE_HYBRID_SEARCH=true but fastembed is not installed; "
            "run: pip install fastembed"
        )
        return False
    settings.embedding_model_cache_path.mkdir(parents=True, exist_ok=True)
    if not embedding_model_cached() and not settings.embedding_allow_hub_download:
        logger.warning(
            "Embedding model not cached at %s and EMBEDDING_ALLOW_HUB_DOWNLOAD=false; "
            "run: python scripts/download_embedding_model.py",
            settings.embedding_model_cache_path,
        )
        return False
    try:
        preload_embedder()
        logger.info(
            "Embedding model ready (%s, cache=%s)",
            settings.embedding_model_id,
            settings.embedding_model_cache_path,
        )
        return True
    except RuntimeError as exc:
        logger.warning("%s", exc)
        return False


def embedding_dims_for_model(model_id: str) -> int:
    try:
        from fastembed import TextEmbedding

        for spec in TextEmbedding.list_supported_models():
            if spec.get("model") == model_id:
                return int(spec.get("dim") or settings.embedding_dims)
    except Exception:
        pass
    return settings.embedding_dims


def _get_embedder(*, force: bool = False):
    global _embedder, _embedder_failed
    if _embedder_failed and not force:
        return None
    if _embedder is not None:
        return _embedder
    if (
        not force
        and settings.enable_hybrid_search
        and settings.embedding_allow_hub_download
    ):
        ensure_embedding_model()
        if _embedder is not None:
            return _embedder

    if settings.embedding_model_id in _LEGACY_MODEL_IDS:
        logger.warning(
            "EMBEDDING_MODEL_ID=%s is prone to incomplete ONNX downloads. "
            "Prefer BAAI/bge-small-en-v1.5 (fastembed default).",
            settings.embedding_model_id,
        )

    try:
        from fastembed import TextEmbedding
    except ImportError:
        logger.info("fastembed not installed; chunk embeddings disabled")
        _embedder_failed = True
        return None

    cache_dir = str(settings.embedding_model_cache_path)
    settings.embedding_model_cache_path.mkdir(parents=True, exist_ok=True)

    try:
        _embedder = TextEmbedding(
            model_name=settings.embedding_model_id,
            cache_dir=cache_dir,
        )
        return _embedder
    except Exception as exc:
        _embedder_failed = True
        logger.warning("embedding model load failed: %s", exc)
        return None


def preload_embedder() -> None:
    """Load the embedding model once; raise with actionable help if download/cache is broken."""
    model = _get_embedder(force=True)
    if model is None:
        cache = settings.embedding_model_cache_path
        raise RuntimeError(
            f"Could not load fastembed model '{settings.embedding_model_id}'.\n"
            f"  1. Run: python scripts/download_embedding_model.py\n"
            f"  2. Or set EMBEDDING_MODEL_ID=BAAI/bge-small-en-v1.5 in backend/.env\n"
            f"  3. If a prior download failed, remove stale cache:\n"
            f"     rm -rf \"{cache}\" \"$TMPDIR/fastembed_cache\""
        )
    probe = list(model.embed(["ping"]))
    if not probe:
        raise RuntimeError("Embedding model loaded but returned no vectors for a test string.")


def reset_embedder_cache() -> None:
    global _embedder, _embedder_failed
    _embedder = None
    _embedder_failed = False


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    model = _get_embedder()
    if not model or not texts:
        return None
    try:
        vectors = list(model.embed(texts))
        return [v.tolist() if hasattr(v, "tolist") else list(v) for v in vectors]
    except Exception as exc:
        logger.warning("embedding failed: %s", exc)
        return None


def l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm <= 0:
        return vec
    return [x / norm for x in vec]


def embedding_to_blob(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def blob_to_embedding(blob: bytes, dims: int | None = None) -> list[float]:
    dims = dims or settings.embedding_dims
    count = len(blob) // 4
    if count != dims:
        dims = count
    return list(struct.unpack(f"{dims}f", blob[: dims * 4]))


def index_chunks_for_document(
    db: Session,
    document_id: str,
    *,
    chunk_rows: list[tuple[str, str]] | None = None,
) -> int:
    """Embed and store vectors for all chunks of a document. Returns count indexed."""
    if not settings.enable_hybrid_search:
        return 0
    if not ensure_embedding_model():
        return 0

    if chunk_rows is None:
        rows = db.execute(
            select(Chunk.id, Chunk.text_content).where(Chunk.document_id == document_id)
        ).all()
        chunk_rows = [(r[0], r[1]) for r in rows]

    if not chunk_rows:
        return 0

    texts = [(c[1] or "")[:2000] for c in chunk_rows]
    vectors = embed_texts(texts)
    if not vectors:
        return 0

    db.execute(delete(ChunkEmbedding).where(
        ChunkEmbedding.chunk_id.in_([c[0] for c in chunk_rows])
    ))
    model_id = settings.embedding_model_id
    dims = len(vectors[0])
    now = utc_now_iso()
    doc = db.get(Document, document_id)
    workspace_id = doc.workspace_id if doc else None
    chunk_vector_rows: list[tuple[str, int, list[float]]] = []
    page_numbers = db.execute(
        select(Chunk.id, Chunk.page_number).where(
            Chunk.id.in_([c[0] for c in chunk_rows])
        )
    ).all()
    page_by_chunk = {r[0]: int(r[1]) for r in page_numbers}

    for (chunk_id, _), raw_vec in zip(chunk_rows, vectors):
        vec = l2_normalize(raw_vec)
        db.add(
            ChunkEmbedding(
                chunk_id=chunk_id,
                document_id=document_id,
                embedding_blob=embedding_to_blob(vec),
                model_id=model_id,
                dims=dims,
                created_at=now,
            )
        )
        chunk_vector_rows.append((chunk_id, page_by_chunk.get(chunk_id, 1), vec))

    from app.services.page_embeddings import upsert_page_embeddings_for_document

    upsert_page_embeddings_for_document(
        db,
        document_id,
        chunk_vectors=chunk_vector_rows,
        workspace_id=workspace_id,
    )
    db.commit()

    from app.services.page_embeddings import _mean_pool
    from app.services.sqlite_vec import (
        delete_chunk_vectors_for_document,
        delete_page_vectors_for_document,
        upsert_chunk_vectors,
        upsert_page_vectors,
    )

    delete_chunk_vectors_for_document(db, document_id)
    delete_page_vectors_for_document(db, document_id)
    upsert_chunk_vectors(
        db,
        rows=[(cid, document_id, vec) for cid, _page, vec in chunk_vector_rows],
    )
    by_page: dict[int, list[list[float]]] = {}
    for _cid, page, vec in chunk_vector_rows:
        by_page.setdefault(int(page), []).append(vec)
    page_vec_rows = [
        (document_id, page, pooled)
        for page, vecs in by_page.items()
        if (pooled := _mean_pool(vecs))
    ]
    upsert_page_vectors(db, rows=page_vec_rows)
    return len(vectors)


def index_document_after_parse(db: Session, document_id: str) -> int:
    chunks = db.scalars(
        select(Chunk).where(Chunk.document_id == document_id)
    ).all()
    return index_chunks_for_document(
        db,
        document_id,
        chunk_rows=[(c.id, c.text_content) for c in chunks],
    )


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    return sum(x * y for x, y in zip(a, b))
