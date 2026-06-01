import pytest

from eval.metrics import ndcg_at_k, precision_at_k, recall_at_k


def test_recall_at_k():
    assert recall_at_k(["a", "b", "c"], {"a", "d"}, 3) == 0.5


def test_precision_at_k():
    assert precision_at_k(["a", "b", "x"], {"a", "b"}, 3) == pytest.approx(2 / 3)


def test_ndcg_perfect():
    assert ndcg_at_k(["a", "b"], {"a", "b"}, 2) == 1.0
