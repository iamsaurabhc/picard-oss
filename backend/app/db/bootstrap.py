import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine


def _column_names(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


def run_migrations(engine: Engine) -> None:
    with engine.begin() as conn:
        mention_cols = _column_names(conn, "entity_mentions")
        if "source" not in mention_cols:
            conn.execute(text("ALTER TABLE entity_mentions ADD COLUMN source TEXT DEFAULT 'rule'"))

        msg_cols = _column_names(conn, "chat_messages")
        if msg_cols and "refused" not in msg_cols:
            conn.execute(text("ALTER TABLE chat_messages ADD COLUMN refused INTEGER DEFAULT 0"))

        doc_cols = _column_names(conn, "documents")
        if doc_cols:
            if "text_source" not in doc_cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN text_source TEXT"))
            if "ocr_engine" not in doc_cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN ocr_engine TEXT"))

        session_cols = _column_names(conn, "chat_sessions")
        if session_cols:
            if "updated_at" not in session_cols:
                conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN updated_at TEXT"))
                conn.execute(text("UPDATE chat_sessions SET updated_at = created_at"))
            if "document_ids_json" not in session_cols:
                conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN document_ids_json TEXT"))

        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
        if "chunk_embeddings" not in tables:
            conn.execute(text("""
                CREATE TABLE chunk_embeddings (
                  chunk_id TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
                  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                  embedding_blob BLOB NOT NULL,
                  model_id TEXT NOT NULL,
                  dims INTEGER NOT NULL,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY (document_id) REFERENCES documents(id)
                )
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_document
                  ON chunk_embeddings(document_id)
            """))


def _init_sql_path() -> Path:
    rel = Path(__file__).parent / "init.sql"
    if rel.is_file():
        return rel
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / "app" / "db" / "init.sql"
        if bundled.is_file():
            return bundled
    raise FileNotFoundError(f"init.sql not found (tried {rel})")


def run_init_sql(engine: Engine) -> None:
    init_path = _init_sql_path()
    sql = init_path.read_text(encoding="utf-8")
    raw = engine.raw_connection()
    try:
        raw.executescript(sql)
        raw.commit()
    finally:
        raw.close()
    run_migrations(engine)
