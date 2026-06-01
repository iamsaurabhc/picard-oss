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


def run_init_sql(engine: Engine) -> None:
    init_path = Path(__file__).parent / "init.sql"
    sql = init_path.read_text(encoding="utf-8")
    raw = engine.raw_connection()
    try:
        raw.executescript(sql)
        raw.commit()
    finally:
        raw.close()
    run_migrations(engine)
