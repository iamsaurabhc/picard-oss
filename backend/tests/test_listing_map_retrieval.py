"""Per-document listing map retrieval: seeds and fair quotas."""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

from app.db.models import Chunk, Document, Workspace
from app.db.session import utc_now_iso
from app.services.entity_extraction.recognizers.rules import normalize_party
from app.services.entity_index import extract_entities_for_document
from app.services.entity_page_chunks import chunks_from_entity_mentions_per_doc
from app.services.listing_map_reduce import retrieve_hits_for_listing_document
from app.services.query_understanding import QueryUnderstanding, TargetEntity


def _seed_doc(db_session, ws_id: str, file_name: str, text: str) -> str:
    now = utc_now_iso()
    doc_id = str(uuid.uuid4())
    db_session.add(
        Document(
            id=doc_id,
            workspace_id=ws_id,
            file_name=file_name,
            local_path=file_name,
            content_hash=str(uuid.uuid4()),
            parse_status="done",
            page_count=1,
            created_at=now,
        )
    )
    db_session.add(
        Chunk(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            page_number=1,
            chunk_type="paragraph",
            bbox_json=json.dumps({"x0": 0, "y0": 0, "x1": 1, "y1": 0.5}),
            text_content=text,
            heading_path="Caption",
            section_key="s1",
            token_count=20,
        )
    )
    db_session.commit()
    extract_entities_for_document(db_session, doc_id)
    return doc_id


def test_per_doc_entity_chunks_fair_quota(db_session):
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="W", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    db_session.commit()

    doc_a = _seed_doc(db_session, ws.id, "A.pdf", "Google LLC is respondent in matter A.")
    doc_b = _seed_doc(db_session, ws.id, "B.pdf", "Google LLC is opposite party in matter B.")

    hits = chunks_from_entity_mentions_per_doc(
        db_session,
        ws.id,
        [doc_a, doc_b],
        per_doc_limit=2,
    )
    by_doc = {doc_a: 0, doc_b: 0}
    for h in hits:
        by_doc[h.document_id] = by_doc.get(h.document_id, 0) + 1
    assert by_doc[doc_a] >= 1
    assert by_doc[doc_b] >= 1


def test_retrieve_hits_seeds_from_entity_pages_when_fts_empty(db_session):
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="W", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    db_session.commit()

    canonical = normalize_party("Google LLC")
    doc_id = _seed_doc(
        db_session,
        ws.id,
        "Only-Entity.pdf",
        "Informants filed against Google LLC under Section 4.",
    )

    understanding = QueryUnderstanding(
        intent="entity_matter_listing",
        target_entity=TargetEntity(
            canonical=canonical,
            surfaces=["Google LLC"],
            resolved_canonicals=[canonical],
        ),
    )

    with patch(
        "app.services.listing_map_reduce.run_search_passes_for_document",
        return_value=[],
    ):
        hits = retrieve_hits_for_listing_document(
            db_session,
            workspace_id=ws.id,
            document_id=doc_id,
            understanding=understanding,
            query="list cases against Google LLC",
            canonicals=[canonical],
            chunks_per_doc=4,
        )

    assert hits
    assert all(h.document_id == doc_id for h in hits)
