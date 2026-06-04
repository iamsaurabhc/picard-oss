"""Regression: inner import of _fts_hit_to_search_hit must not shadow module import."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from app.db.models import Document, Workspace
from app.db.session import utc_now_iso
from app.services.entity_listing_retrieval import entity_listing_retrieve_with_progress
from app.services.query_understanding import QueryUnderstanding, TargetEntity
from app.services.retrieval_progress import consume_retrieval_generator


def test_listing_return_does_not_shadow_fts_converter(db_session):
    """When diverse hits exist, return path must not raise UnboundLocalError."""
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="W", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    doc_id = str(uuid.uuid4())
    db_session.add(
        Document(
            id=doc_id,
            workspace_id=ws.id,
            file_name="g.pdf",
            local_path="g.pdf",
            content_hash=str(uuid.uuid4()),
            parse_status="done",
            page_count=1,
            created_at=now,
        )
    )
    hit = MagicMock(chunk_id="c1", document_id=doc_id, score=0.1)
    converted = MagicMock()
    understanding = QueryUnderstanding(
        intent="entity_matter_listing",
        target_entity=TargetEntity(
            canonical="Google LLC",
            surfaces=["Google"],
            resolved_canonicals=["Google LLC"],
        ),
    )

    with (
        patch(
            "app.services.entity_listing_retrieval.discover_listing_documents",
            return_value=([(doc_id, 1)], {"documents_total_discovered": 1, "discovery_sources": {}}),
        ),
        patch(
            "app.services.entity_listing_retrieval.lookup_pages_for_party_in_document",
            return_value=[1],
        ),
        patch(
            "app.services.entity_listing_retrieval.run_search_passes_for_document",
            return_value=[hit],
        ),
        patch(
            "app.services.entity_listing_retrieval._apply_doc_quotas",
            return_value=[hit],
        ),
        patch(
            "app.services.entity_listing_retrieval._fts_hit_to_search_hit",
            side_effect=lambda h: converted,
        ) as conv,
    ):
        _, (hits, _) = consume_retrieval_generator(
            entity_listing_retrieve_with_progress(
                db_session,
                understanding,
                workspace_id=ws.id,
                query="list case details against google",
            )
        )

    assert hits == [converted]
    conv.assert_called_once_with(hit)
