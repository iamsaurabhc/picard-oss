from datetime import datetime, timezone
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings
from app.db.bootstrap import run_init_sql


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    from app.services.sqlite_vec import _probe_vec_backend

    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
    try_load = getattr(dbapi_connection, "load_extension", None)
    if callable(try_load):
        from app.services.sqlite_vec import try_load_sqlite_vec

        try_load_sqlite_vec(dbapi_connection)
    else:
        _probe_vec_backend()


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db() -> None:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    run_init_sql(engine)
    from app.services.workflows_store import seed_builtin_workflows

    db = SessionLocal()
    try:
        seed_builtin_workflows(db)
        db.commit()
    finally:
        db.close()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
