"""Page vector mean-pool and search tests."""

from app.services.chunk_embeddings import l2_normalize
from app.services.page_embeddings import _mean_pool


def test_mean_pool_single_vector():
    v = l2_normalize([1.0, 0.0, 0.0])
    out = _mean_pool([v])
    assert len(out) == 3
    assert abs(out[0] - 1.0) < 0.01


def test_mean_pool_averages():
    a = l2_normalize([1.0, 0.0])
    b = l2_normalize([0.0, 1.0])
    out = _mean_pool([a, b])
    assert len(out) == 2
    assert abs(out[0] - out[1]) < 0.2


def test_vector_page_scores_disabled_without_hybrid(monkeypatch, db_session):
    from app.config import settings
    from app.services.hybrid_search import vector_page_scores

    monkeypatch.setattr(settings, "enable_hybrid_search", False)
    scores = vector_page_scores(
        db_session,
        queries=["test"],
        workspace_id="ws",
        document_ids=["doc"],
    )
    assert scores == {}
