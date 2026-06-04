import json
import os
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.bootstrap import run_init_sql, run_migrations
from app.db.models import Base
from app.db.session import get_db
from app.main import app


def resolve_corpus_db_path() -> Path | None:
    env_url = os.environ.get("PICARD_TEST_DATABASE_URL")
    if env_url and env_url.startswith("sqlite:///"):
        path = Path(env_url.removeprefix("sqlite:///"))
        if path.exists():
            return path
    repo_root = Path(__file__).resolve().parents[2]
    snapshot = repo_root / "backend" / "test" / "fixtures" / "corpus" / "picard-corpus.db"
    if snapshot.exists():
        return snapshot
    local = repo_root / ".picard-data" / "picard.db"
    if local.exists():
        return local
    return None


@pytest.fixture(scope="session")
def corpus_db_path():
    path = resolve_corpus_db_path()
    if not path:
        pytest.skip("No corpus DB found; run export_test_corpus.py or use .picard-data/picard.db")
    return path


@pytest.fixture(scope="session")
def corpus_engine(corpus_db_path):
    url = f"sqlite:///{corpus_db_path}"
    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    run_migrations(engine)
    return engine


@pytest.fixture()
def corpus_session(corpus_engine):
    Session = sessionmaker(bind=corpus_engine, autocommit=False, autoflush=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def corpus_client(corpus_engine, monkeypatch):
    Session = sessionmaker(bind=corpus_engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("app.main.init_db", lambda: None)
    monkeypatch.setattr("app.config.settings.enable_llm_query_understanding", False)
    monkeypatch.setattr("app.config.settings.enable_context_ranker", False)

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture()
def db_engine(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    data_dir = tmp_path / "data"
    url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("PICARD_DATA_DIR", str(data_dir))

    from app.config import settings

    settings.picard_data_dir = data_dir
    settings.database_url = url

    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    run_init_sql(engine)
    Base.metadata.create_all(bind=engine)
    from app.services.workflows_store import seed_builtin_workflows

    seed_session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    try:
        seed_builtin_workflows(seed_session)
        seed_session.commit()
    finally:
        seed_session.close()
    return engine


@pytest.fixture()
def db_session(db_engine):
    TestingSessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def test_sessionmaker(db_engine):
    return sessionmaker(bind=db_engine, autocommit=False, autoflush=False)


_PLANNER_FIXTURES_PATH = Path(__file__).resolve().parent / "fixtures" / "query_planner_responses.json"


def _load_planner_fixture(name: str) -> dict:
    data = json.loads(_PLANNER_FIXTURES_PATH.read_text())
    return data[name]


@pytest.fixture()
def mock_query_planner(monkeypatch):
    """Patch _llm_understand to return fixture JSON for named planner responses."""

    def _apply(name: str):
        payload = _load_planner_fixture(name)

        def _fake_llm(query: str, document_context=None):
            from app.services.query_understanding import (
                FtsPlan,
                QueryConstraint,
                QueryUnderstanding,
                SearchPass,
                _parse_search_passes,
                _parse_target_entity,
            )

            te = _parse_target_entity(payload.get("target_entity"))
            constraints = [
                QueryConstraint(**c) for c in payload.get("constraints", []) if isinstance(c, dict)
            ]
            fts_data = payload.get("fts") or {}
            return QueryUnderstanding(
                retrieval_mode=payload.get("retrieval_mode", "SIMPLE"),
                intent=payload.get("intent", "general"),
                target_entity=te,
                constraints=constraints,
                fts=FtsPlan(
                    must_terms=fts_data.get("must_terms", []),
                    should_terms=fts_data.get("should_terms", []),
                    phrases=fts_data.get("phrases", []),
                    operator=fts_data.get("operator", "AND"),
                ),
                search_passes=_parse_search_passes(payload.get("search_passes") or []),
                coverage_goal=str(payload.get("coverage_goal") or ""),
                confidence=float(payload.get("confidence", 0.9)),
                used_llm=True,
            )

        monkeypatch.setattr(
            "app.services.query_understanding._llm_understand",
            _fake_llm,
        )
        monkeypatch.setattr("app.config.settings.enable_llm_query_understanding", True)
        return _fake_llm

    return _apply


@pytest.fixture(autouse=True)
def _reset_slm_flags():
    """Isolate tests that toggle SLM feature flags."""
    settings.enable_llm_query_understanding = True
    settings.enable_regex_nlp = False
    settings.enable_slm_entity_extract = True
    settings.enable_rule_entity_extract = False
    yield
    settings.enable_llm_query_understanding = True
    settings.enable_regex_nlp = False
    settings.enable_slm_entity_extract = True
    settings.enable_rule_entity_extract = False
    settings.enable_context_ranker = True
    settings.enable_excerpt_selector = True
    settings.query_planner_repair_on_zero_hits = True


@pytest.fixture()
def client(db_engine, test_sessionmaker, tmp_path, monkeypatch):
    def override_get_db():
        db = test_sessionmaker()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("app.main.init_db", lambda: None)
    monkeypatch.setattr("app.main.recover_stuck_parsing_documents", lambda: 0)
    monkeypatch.setattr("app.services.ingestion.SessionLocal", test_sessionmaker)

    from app.config import settings

    data_dir = tmp_path / "data"
    monkeypatch.setattr(settings, "picard_data_dir", data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "pdfs").mkdir(parents=True, exist_ok=True)

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
