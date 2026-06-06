"""sqlite-vec ANN integration with BLOB brute-force fallback."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)

_vec_available: bool | None = None
_vec_load_attempted = False
_vec_use_apsw = False


class _ApswCursor:
    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self._rows: list[Any] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _ApswCursor:
        if params:
            self._rows = list(self._conn.execute(sql, params))
        else:
            self._rows = list(self._conn.execute(sql))
        return self

    def fetchall(self) -> list[Any]:
        return self._rows


class _ApswAdapter:
    """Minimal sqlite3-like wrapper for APSW connections."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def cursor(self) -> _ApswCursor:
        return _ApswCursor(self._conn)

    def commit(self) -> None:
        return None


def connection_supports_load_extension(dbapi_connection) -> bool:
    return callable(getattr(dbapi_connection, "load_extension", None))


def _probe_apsw_vec() -> bool:
    try:
        import apsw
        import sqlite_vec

        conn = apsw.Connection(":memory:")
        conn.enableloadextension(True)
        sqlite_vec.load(conn)
        conn.execute("select vec_version()").fetchone()
        return True
    except Exception:
        return False


def _probe_vec_backend() -> bool:
    """Detect sqlite-vec via APSW (Py3.13+) or stdlib load_extension."""
    global _vec_available, _vec_load_attempted, _vec_use_apsw
    if _vec_load_attempted:
        return bool(_vec_available)
    _vec_load_attempted = True

    if _probe_apsw_vec():
        _vec_available = True
        _vec_use_apsw = True
        logger.info("sqlite-vec ANN enabled via APSW")
        return True

    try:
        import sqlite3
        import sqlite_vec

        db = sqlite3.connect(":memory:")
        if connection_supports_load_extension(db):
            sqlite_vec.load(db)
            db.execute("select vec_version()").fetchone()
            _vec_available = True
            _vec_use_apsw = False
            logger.info("sqlite-vec ANN enabled via stdlib sqlite3")
            return True
    except Exception as exc:
        logger.warning("sqlite-vec unavailable (%s); using BLOB fallback", exc)

    _vec_available = False
    _vec_use_apsw = False
    logger.info(
        "sqlite-vec ANN disabled — install apsw + sqlite-vec for KNN "
        "(BLOB vector scan still works)"
    )
    return False


def try_load_sqlite_vec(dbapi_connection) -> bool:
    """Load sqlite-vec on a stdlib DBAPI connection when supported."""
    if _vec_use_apsw:
        return bool(_vec_available)
    if not _probe_vec_backend():
        return False
    if _vec_use_apsw:
        return True
    if not connection_supports_load_extension(dbapi_connection):
        return False
    try:
        import sqlite_vec

        sqlite_vec.load(dbapi_connection)
        return True
    except Exception:
        return False


def sqlite_vec_available() -> bool:
    _probe_vec_backend()
    return bool(_vec_available)


def vec_backend_name() -> str:
    _probe_vec_backend()
    if not _vec_available:
        return "blob-scan"
    return "sqlite-vec-apsw" if _vec_use_apsw else "sqlite-vec"


def serialize_vector(vec: list[float]) -> bytes:
    from sqlite_vec import serialize_float32

    return serialize_float32(vec)


def page_key(document_id: str, page_number: int) -> str:
    return f"{document_id}:{page_number}"


def parse_page_key(key: str) -> tuple[str, int] | None:
    if ":" not in key:
        return None
    doc_id, _, page_s = key.partition(":")
    try:
        return doc_id, int(page_s)
    except ValueError:
        return None


def _db_path_from_session(db: Session) -> str:
    url = db.get_bind().url
    database = url.database
    if not database or database == ":memory:":
        raise RuntimeError("sqlite-vec requires a file-backed SQLite database")
    return str(database)


def _open_apsw_vec_connection(db: Session) -> _ApswAdapter:
    import apsw
    import sqlite_vec

    path = _db_path_from_session(db)
    conn = apsw.Connection(path)
    conn.enableloadextension(True)
    sqlite_vec.load(conn)
    return _ApswAdapter(conn)


def _vec_connection(db: Session):
    if not _probe_vec_backend():
        return None
    if _vec_use_apsw:
        return _open_apsw_vec_connection(db)
    return db.connection().connection.dbapi_connection


def ensure_vec_schema(db: Session, *, dims: int | None = None) -> bool:
    """Create vec0 tables when sqlite-vec is loaded."""
    conn = _vec_connection(db)
    if conn is None:
        return False
    dim = dims or settings.embedding_dims
    cursor = conn.cursor()
    cursor.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors USING vec0(
          chunk_id TEXT PRIMARY KEY,
          embedding float[{dim}] distance_metric=cosine,
          document_id TEXT partition key
        )
        """
    )
    cursor.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS page_vectors USING vec0(
          page_key TEXT PRIMARY KEY,
          embedding float[{dim}] distance_metric=cosine,
          document_id TEXT partition key
        )
        """
    )
    conn.commit()
    return True


def _prepare_for_apsw_write(db: Session) -> None:
    """Release SQLAlchemy transaction locks before APSW writes the same DB file."""
    db.commit()


def upsert_chunk_vectors(
    db: Session,
    *,
    rows: list[tuple[str, str, list[float]]],
) -> int:
    """Upsert chunk_id, document_id, normalized vector into chunk_vectors vec0."""
    if not rows:
        return 0
    _prepare_for_apsw_write(db)
    if not ensure_vec_schema(db):
        return 0
    conn = _vec_connection(db)
    assert conn is not None
    cursor = conn.cursor()
    for chunk_id, document_id, vec in rows:
        cursor.execute("DELETE FROM chunk_vectors WHERE chunk_id = ?", (chunk_id,))
        cursor.execute(
            """
            INSERT INTO chunk_vectors(chunk_id, embedding, document_id)
            VALUES (?, ?, ?)
            """,
            (chunk_id, serialize_vector(vec), document_id),
        )
    conn.commit()
    return len(rows)


def delete_chunk_vectors_for_document(db: Session, document_id: str) -> None:
    _prepare_for_apsw_write(db)
    if not ensure_vec_schema(db):
        return
    conn = _vec_connection(db)
    assert conn is not None
    conn.cursor().execute(
        """
        DELETE FROM chunk_vectors
        WHERE chunk_id IN (SELECT id FROM chunks WHERE document_id = ?)
        """,
        (document_id,),
    )
    conn.commit()


def upsert_page_vectors(
    db: Session,
    *,
    rows: list[tuple[str, int, list[float]]],
) -> int:
    """Upsert document_id, page_number, normalized vector into page_vectors vec0."""
    if not rows:
        return 0
    _prepare_for_apsw_write(db)
    if not ensure_vec_schema(db):
        return 0
    conn = _vec_connection(db)
    assert conn is not None
    cursor = conn.cursor()
    for document_id, page_number, vec in rows:
        key = page_key(document_id, page_number)
        cursor.execute("DELETE FROM page_vectors WHERE page_key = ?", (key,))
        cursor.execute(
            """
            INSERT INTO page_vectors(page_key, embedding, document_id)
            VALUES (?, ?, ?)
            """,
            (key, serialize_vector(vec), document_id),
        )
    conn.commit()
    return len(rows)


def delete_page_vectors_for_document(db: Session, document_id: str) -> None:
    _prepare_for_apsw_write(db)
    if not ensure_vec_schema(db):
        return
    conn = _vec_connection(db)
    assert conn is not None
    conn.cursor().execute(
        "DELETE FROM page_vectors WHERE document_id = ?",
        (document_id,),
    )
    conn.commit()


def knn_chunk_ids(
    db: Session,
    *,
    query_vec: list[float],
    workspace_id: str,
    document_ids: list[str] | None,
    top_k: int,
) -> list[tuple[str, float]]:
    """Return (chunk_id, similarity) using vec0 KNN when available."""
    if not ensure_vec_schema(db):
        return []

    conn = _vec_connection(db)
    assert conn is not None
    q_blob = serialize_vector(query_vec)
    cursor = conn.cursor()

    if document_ids and len(document_ids) == 1:
        cursor.execute(
            """
            SELECT chunk_id, distance
            FROM chunk_vectors
            WHERE embedding MATCH ?
              AND k = ?
              AND document_id = ?
            ORDER BY distance
            """,
            (q_blob, top_k, document_ids[0]),
        )
        return [(str(r[0]), 1.0 - float(r[1])) for r in cursor.fetchall()]

    fetch_k = max(top_k * 8, top_k)
    cursor.execute(
        """
        SELECT chunk_id, distance
        FROM chunk_vectors
        WHERE embedding MATCH ?
          AND k = ?
        ORDER BY distance
        """,
        (q_blob, fetch_k),
    )
    raw = [(str(r[0]), float(r[1])) for r in cursor.fetchall()]
    if not raw:
        return []

    ids = [r[0] for r in raw]
    stmt = text(
        """
        SELECT c.id, d.workspace_id, c.document_id
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.id IN :ids
        """
    ).bindparams(bindparam("ids", expanding=True))
    meta_rows = db.execute(stmt, {"ids": ids}).all()
    id_to_dist = dict(raw)
    doc_set = set(document_ids or [])
    filtered: list[tuple[str, float]] = []
    for chunk_id, ws, doc_id in meta_rows:
        if ws != workspace_id:
            continue
        if document_ids and doc_id not in doc_set:
            continue
        filtered.append((chunk_id, 1.0 - id_to_dist.get(chunk_id, 1.0)))
    filtered.sort(key=lambda x: -x[1])
    return filtered[:top_k]


def knn_page_scores(
    db: Session,
    *,
    query_vec: list[float],
    document_id: str,
    top_k: int,
) -> dict[int, float]:
    """Doc-scoped page KNN; returns page_number -> similarity."""
    if not ensure_vec_schema(db):
        return {}
    conn = _vec_connection(db)
    assert conn is not None
    q_blob = serialize_vector(query_vec)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT page_key, distance
        FROM page_vectors
        WHERE embedding MATCH ?
          AND k = ?
          AND document_id = ?
        ORDER BY distance
        """,
        (q_blob, top_k, document_id),
    )
    out: dict[int, float] = {}
    for key, dist in cursor.fetchall():
        parsed = parse_page_key(str(key))
        if not parsed:
            continue
        _doc, page = parsed
        out[page] = max(out.get(page, 0.0), 1.0 - float(dist))
    return out


def backfill_chunk_vectors_from_blobs(db: Session, document_id: str) -> int:
    """Populate chunk_vectors vec0 from chunk_embeddings BLOBs."""
    from app.services.chunk_embeddings import blob_to_embedding

    rows = db.execute(
        text(
            """
            SELECT ce.chunk_id, ce.document_id, ce.embedding_blob, ce.dims
            FROM chunk_embeddings ce
            WHERE ce.document_id = :doc_id
            """
        ),
        {"doc_id": document_id},
    ).all()
    payload = [
        (r[0], r[1], blob_to_embedding(r[2], r[3]))
        for r in rows
    ]
    delete_chunk_vectors_for_document(db, document_id)
    return upsert_chunk_vectors(db, rows=payload)


def backfill_page_vectors_from_blobs(db: Session, document_id: str) -> int:
    """Populate page_vectors vec0 from page_embeddings BLOBs."""
    from app.services.chunk_embeddings import blob_to_embedding

    rows = db.execute(
        text(
            """
            SELECT document_id, page_number, embedding_blob, dims
            FROM page_embeddings
            WHERE document_id = :doc_id
            """
        ),
        {"doc_id": document_id},
    ).all()
    payload = [
        (r[0], int(r[1]), blob_to_embedding(r[2], r[3]))
        for r in rows
    ]
    delete_page_vectors_for_document(db, document_id)
    return upsert_page_vectors(db, rows=payload)
