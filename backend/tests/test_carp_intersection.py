import pytest

from app.services.carp import run_carp
from app.services.constraint_planner import Constraint
from tests.corpus_constants import CARP_INTERSECTION_PAGE, DOCUMENT_ID, WORKSPACE_ID


@pytest.mark.corpus
def test_carp_intersection_page_3(corpus_session):
    constraints = [
        Constraint("party", "supreme court", ["Supreme Court"]),
        Constraint("identifier", "refused", ["refused"]),
    ]
    result = run_carp(
        corpus_session,
        query="case context supreme court refused",
        workspace_id=WORKSPACE_ID,
        constraints=constraints,
        document_ids=[DOCUMENT_ID],
    )
    assert not result.refused
    assert result.bundles
    pages = {(b.document_id, b.page_start) for b in result.bundles}
    assert (DOCUMENT_ID, CARP_INTERSECTION_PAGE) in pages


@pytest.mark.corpus
def test_carp_refuse_non_intersecting(corpus_session):
    constraints = [
        Constraint("party", "janet chester", ["Janet Chester"]),
        Constraint("identifier", "agreement that", ["agreement that"]),
    ]
    result = run_carp(
        corpus_session,
        query="case context for janet chester and supreme court",
        workspace_id=WORKSPACE_ID,
        constraints=constraints,
        document_ids=[DOCUMENT_ID],
    )
    assert result.refused
    assert result.retrieval_diagnostics.get("intersection_pages", 0) == 0
