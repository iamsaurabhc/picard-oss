"""Party-scoped discovery must rank informant documents above generic CCI orders."""

from __future__ import annotations

import json
import uuid

from app.db.models import Chunk, Document, Workspace
from app.db.session import utc_now_iso
from app.services.entity_extraction import extract_entities_for_document
from app.services.entity_index import (
    _surface_matches_party_canonical,
    resolve_party_canonicals,
    sanitize_party_canonicals,
)
from app.services.listing_discovery import discover_listing_documents
from app.services.query_understanding import (
    QueryUnderstanding,
    _apply_overview_fields,
    _party_from_filed_by_phrase,
)


def test_surface_match_rejects_single_letter_party_noise():
    assert not _surface_matches_party_canonical("Kshitiz Arya", "a")
    assert not _surface_matches_party_canonical("Kshitiz Arya", "i")
    assert _surface_matches_party_canonical("Kshitiz Arya", "kshitiz arya")


def test_sanitize_party_canonicals_drops_noise():
    raw = ["a", "i", "kshitiz arya", "kshitiz arya\nflat no"]
    assert sanitize_party_canonicals(raw) == ["kshitiz arya"]


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
            heading_path="Body",
            section_key="s1",
            token_count=80,
        )
    )
    db_session.commit()
    extract_entities_for_document(db_session, doc_id)
    return doc_id


def test_party_scoped_discovery_prefers_informant_doc(db_session):
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="CCI", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    db_session.commit()

    kshitiz_doc = _seed_doc(
        db_session,
        ws.id,
        "1920201652249245.pdf",
        "The Information was filed by Mr. Kshitiz Arya and Mr. Purushottam Anand against Google.",
    )
    _seed_doc(
        db_session,
        ws.id,
        "07-and-3020121652434133.pdf",
        "Case Nos. 07 and 30 of 2012. Matrimony.com Limited filed case details against Google LLC.",
    )

    q = "give in-depth case details filed by Kshitiz Arya in CCI"
    party = _party_from_filed_by_phrase(q)
    assert party is not None
    u = QueryUnderstanding(intent="case_overview")
    u = _apply_overview_fields(u, q, db=db_session, workspace_id=ws.id)
    assert u.target_entity is not None

    resolved = resolve_party_canonicals(
        db_session,
        ws.id,
        canonical=party.canonical,
        surfaces=party.surfaces,
    )
    assert "a" not in resolved
    assert "i" not in resolved

    doc_rows, diag = discover_listing_documents(
        db_session,
        u,
        workspace_id=ws.id,
        document_ids=None,
        query=q,
    )
    assert doc_rows
    assert doc_rows[0][0] == kshitiz_doc
    assert diag["discovery_sources"]["union_total"] >= 1
