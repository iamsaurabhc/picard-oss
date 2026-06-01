import pytest

from eval.baselines import or_bm25_search
from tests.corpus_constants import DOCUMENT_ID, WORKSPACE_ID


@pytest.mark.corpus
def test_or_bm25_returns_hits(corpus_session):
    ids = or_bm25_search(
        corpus_session,
        terms=["supreme", "court", "refused"],
        workspace_id=WORKSPACE_ID,
        document_ids=[DOCUMENT_ID],
    )
    assert isinstance(ids, list)
