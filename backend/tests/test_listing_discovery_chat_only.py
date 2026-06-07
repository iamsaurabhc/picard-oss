"""Chat-first listing discovery without tabular_review_id."""

from __future__ import annotations

import json
import uuid

from app.db.models import Chunk, Document, Workspace
from app.db.session import utc_now_iso
from app.services.entity_extraction.recognizers.rules import normalize_party
from app.services.entity_extraction import extract_entities_for_document
from app.services.listing_discovery import discover_listing_documents
from app.services.listing_map_reduce import should_use_listing_map_reduce
from app.services.query_understanding import QueryUnderstanding, TargetEntity


def _seed_google_doc(db_session, ws_id: str, file_name: str, text: str) -> str:
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
            token_count=40,
        )
    )
    db_session.commit()
    extract_entities_for_document(db_session, doc_id)
    return doc_id


def test_chat_only_discovery_finds_multiple_docs_via_fts(db_session):
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="CCI", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    db_session.commit()

    canonical = normalize_party("Google LLC")
    doc_ids = []
    for i in range(4):
        doc_ids.append(
            _seed_google_doc(
                db_session,
                ws.id,
                f"order-{i}.pdf",
                f"Informants filed against Google LLC in matter {i} under the Competition Act.",
            )
        )

    understanding = QueryUnderstanding(
        intent="entity_matter_listing",
        target_entity=TargetEntity(
            canonical=canonical,
            surfaces=["Google"],
            resolved_canonicals=[canonical],
        ),
    )

    doc_rows, diag = discover_listing_documents(
        db_session,
        understanding,
        workspace_id=ws.id,
        document_ids=None,
        query="list all case details against google in CCI",
        tabular_review_id=None,
    )

    found = {d for d, _ in doc_rows}
    assert len(found) >= 4
    assert diag["discovery_sources"]["fts"] > 0
    assert diag["documents_total_discovered"] >= 4


def test_chat_only_discovery_respects_document_scope(db_session):
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="CCI", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    db_session.commit()

    canonical = normalize_party("Google LLC")
    in_scope = _seed_google_doc(
        db_session,
        ws.id,
        "in.pdf",
        "Google LLC is the opposite party in this CCI matter.",
    )
    out_scope = _seed_google_doc(
        db_session,
        ws.id,
        "out.pdf",
        "Google LLC appears as respondent in another matter.",
    )

    understanding = QueryUnderstanding(
        intent="entity_matter_listing",
        target_entity=TargetEntity(
            canonical=canonical,
            surfaces=["Google"],
            resolved_canonicals=[canonical],
        ),
    )

    doc_rows, _ = discover_listing_documents(
        db_session,
        understanding,
        workspace_id=ws.id,
        document_ids=[in_scope],
        query="list cases against google",
        tabular_review_id=None,
    )

    found = {d for d, _ in doc_rows}
    assert in_scope in found
    assert out_scope not in found


def test_map_reduce_triggers_without_tabular(db_session):
    assert should_use_listing_map_reduce(["d1", "d2", "d3", "d4"])
    assert not should_use_listing_map_reduce(["d1", "d2"])
    assert not should_use_listing_map_reduce(["d1"])


def test_discovery_validates_fts_only_docs_without_target_party(db_session):
    """FTS-only docs that don't mention the target party are dropped."""
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="CCI", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    db_session.commit()

    canonical = normalize_party("Google LLC")
    google_doc = _seed_google_doc(
        db_session,
        ws.id,
        "google-case.pdf",
        "Informants filed against Google LLC under the Competition Act.",
    )
    generic_doc = _seed_google_doc(
        db_session,
        ws.id,
        "chester-v-waverly.pdf",
        (
            "Chester v Municipality of Waverly. The court discussed case details "
            "of negligence. The plaintiff sought damages."
        ),
    )

    understanding = QueryUnderstanding(
        intent="entity_matter_listing",
        target_entity=TargetEntity(
            canonical=canonical,
            surfaces=["Google"],
            resolved_canonicals=[canonical],
        ),
    )

    doc_rows, diag = discover_listing_documents(
        db_session,
        understanding,
        workspace_id=ws.id,
        document_ids=None,
        query="list all case details against google",
        tabular_review_id=None,
    )

    found = {d for d, _ in doc_rows}
    assert google_doc in found
    assert generic_doc not in found
    assert "fts_only_dropped" in diag
    assert diag["fts_only_dropped"] >= 0
