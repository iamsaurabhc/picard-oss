"""sqlite-vec helpers and routing guards."""

from app.services.sqlite_vec import page_key, parse_page_key, sqlite_vec_available


def test_page_key_roundtrip():
    key = page_key("doc-1", 3)
    assert parse_page_key(key) == ("doc-1", 3)


def test_sqlite_vec_graceful_without_extension():
    # Python builds without load_extension fall back to BLOB scan
    assert sqlite_vec_available() in (True, False)


def test_vector_search_routing_uses_page_embeddings_only(monkeypatch, db_session):
    from app.config import settings
    from app.services.hybrid_search import vector_page_scores
    from app.services import page_embeddings as pe

    monkeypatch.setattr(settings, "enable_hybrid_search", True)
    calls = {"blob": 0, "knn": 0}

    def fake_knn(*args, **kwargs):
        calls["knn"] += 1
        return {1: 0.9}

    def fake_load(*args, **kwargs):
        calls["blob"] += 1
        return []

    monkeypatch.setattr("app.services.sqlite_vec.sqlite_vec_available", lambda: True)
    monkeypatch.setattr("app.services.sqlite_vec.knn_page_scores", fake_knn)
    monkeypatch.setattr(pe, "_load_page_rows", fake_load)

    scores = vector_page_scores(
        db_session,
        queries=["negligence"],
        workspace_id="ws",
        document_ids=["doc-1"],
        top_k_per_query=4,
    )
    assert scores.get(1, 0) > 0
    assert calls["knn"] >= 1
    assert calls["blob"] == 0
