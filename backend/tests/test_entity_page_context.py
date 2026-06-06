"""Entity-ranked page context for listing."""

from __future__ import annotations

import json
import uuid

from app.db.models import Chunk, Document, Workspace
from app.db.session import utc_now_iso
from app.services.entity_extraction.recognizers.rules import normalize_party
from app.services.entity_index import extract_entities_for_document
from app.services.entity_page_context import (
    candidate_pages_for_document,
    hits_from_ranked_pages,
    party_canonicals_from_understanding,
    rank_pages_for_listing,
    retrieve_listing_page_hits,
)
from app.services.query_understanding import QueryConstraint, QueryUnderstanding, TargetEntity


def _seed_doc(db_session, ws_id: str, file_name: str, pages: list[str]) -> str:
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
            page_count=len(pages),
            created_at=now,
        )
    )
    for i, text in enumerate(pages, start=1):
        db_session.add(
            Chunk(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                page_number=i,
                chunk_type="paragraph",
                bbox_json=json.dumps({"x0": 0, "y0": 0, "x1": 1, "y1": 0.5}),
                text_content=text,
                heading_path="Caption",
                section_key=f"s{i}",
                token_count=20,
            )
        )
    db_session.commit()
    extract_entities_for_document(db_session, doc_id)
    return doc_id


def test_party_canonicals_from_constraints(db_session):
    u = QueryUnderstanding(
        intent="entity_matter_listing",
        constraints=[
            QueryConstraint(type="party", canonical="google llc", surfaces=["Google LLC"]),
            QueryConstraint(type="party", canonical="cuts", surfaces=["CUTS"]),
        ],
    )
    canonicals = party_canonicals_from_understanding(u)
    assert "google llc" in canonicals
    assert "cuts" in canonicals


def test_retrieve_listing_page_hits_returns_full_page_text(db_session):
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="W", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    db_session.commit()

    canonical = normalize_party("Google LLC")
    doc_id = _seed_doc(
        db_session,
        ws.id,
        "Matter.pdf",
        [
            "Informant CUTS filed against Google LLC as opposite party under Section 4.",
            "Unrelated administrative notice.",
        ],
    )

    understanding = QueryUnderstanding(
        intent="entity_matter_listing",
        target_entity=TargetEntity(
            canonical=canonical,
            surfaces=["Google LLC"],
            resolved_canonicals=[canonical],
        ),
    )

    hits, diag = retrieve_listing_page_hits(
        db_session,
        workspace_id=ws.id,
        document_id=doc_id,
        understanding=understanding,
        query="list case details involving Google LLC",
        canonicals=[canonical],
    )
    assert hits
    assert diag.get("page_level") is True
    assert any("Google LLC" in (h.text_content or "") for h in hits)
    assert any(h.page_number == 1 for h in hits)


def test_rank_pages_caps_large_documents(db_session):
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="W", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    db_session.commit()

    canonical = normalize_party("Google LLC")
    pages = ["Google LLC opposite party on page %d." % i for i in range(1, 61)]
    doc_id = _seed_doc(db_session, ws.id, "Big.pdf", pages)

    understanding = QueryUnderstanding(
        intent="entity_matter_listing",
        target_entity=TargetEntity(
            canonical=canonical,
            surfaces=["Google LLC"],
            resolved_canonicals=[canonical],
        ),
    )
    candidates = candidate_pages_for_document(
        db_session,
        workspace_id=ws.id,
        document_id=doc_id,
        understanding=understanding,
        query="Google LLC",
        canonicals=[canonical],
    )
    ranked = rank_pages_for_listing(
        db_session,
        workspace_id=ws.id,
        document_id=doc_id,
        pages=candidates,
        query="Google LLC",
        understanding=understanding,
        canonicals=[canonical],
    )
    from app.config import settings

    assert len(ranked) <= settings.listing_max_pages_per_doc
