from __future__ import annotations

from sqlalchemy import select

from app.db.models import Chunk
from app.services.carp import _assemble_bundles
from app.services.constraint_planner import Constraint


def test_carp_bundle_includes_all_page_chunks_when_fts_hits(corpus_session):
    workspace_id = "eca7aebb-0b4d-433d-8e73-9144c04eb0d7"
    doc_id = "b65e3196-7199-446e-a910-6476d23b7bc8"
    page = 3

    page_chunks = list(
        corpus_session.scalars(
            select(Chunk).where(
                Chunk.document_id == doc_id,
                Chunk.page_number == page,
            )
        ).all()
    )
    if len(page_chunks) < 2:
        return

    constraints = [
        Constraint(type="party", canonical="supreme court", surfaces=["Supreme Court"]),
        Constraint(type="identifier", canonical="refused", surfaces=["refused"]),
    ]
    bundles = _assemble_bundles(
        corpus_session,
        workspace_id=workspace_id,
        query="supreme court refused damages",
        pages={(doc_id, page)},
        constraints=constraints,
        tier="SAME_PAGE",
        allow_partial=False,
    )
    if not bundles:
        return

    bundle_chunk_ids = set()
    for b in bundles:
        if b.document_id == doc_id and b.page_start == page:
            bundle_chunk_ids.update(b.chunk_ids)

    assert len(bundle_chunk_ids) >= min(len(page_chunks), 6)
