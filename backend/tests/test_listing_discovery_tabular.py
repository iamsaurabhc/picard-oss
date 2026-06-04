"""Unified listing discovery: tabular union with sparse entity index."""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

from app.db.models import Document, TabularCell, TabularReview, Workspace
from app.db.session import utc_now_iso
from app.services.listing_discovery import discover_listing_documents
from app.services.query_understanding import QueryUnderstanding, TargetEntity
from app.services.tabular import (
    build_tabular_document_metadata_block,
    discover_tabular_listing_documents,
)


def _make_review(db_session, ws_id: str, doc_ids: list[str], cells: list[tuple[str, str, str]]) -> str:
    now = utc_now_iso()
    rid = str(uuid.uuid4())
    cols = json.dumps(
        [
            {"key": "parties", "label": "Parties", "format": "text", "prompt": "List parties"},
            {"key": "statute", "label": "Statute / Jurisdiction", "format": "text", "prompt": "Statute"},
        ]
    )
    db_session.add(
        TabularReview(
            id=rid,
            workspace_id=ws_id,
            title="Regulatory review",
            columns_config_json=cols,
            document_ids_json=json.dumps(doc_ids),
            created_at=now,
        )
    )
    for doc_id, col_key, summary in cells:
        db_session.add(
            TabularCell(
                id=str(uuid.uuid4()),
                review_id=rid,
                document_id=doc_id,
                column_key=col_key,
                summary=summary,
                status="done",
            )
        )
    db_session.commit()
    return rid


def test_discover_tabular_scores_google_docs(db_session):
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="CCI", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    doc_ids = []
    for name in ("order-a.pdf", "order-b.pdf", "unrelated.pdf"):
        did = str(uuid.uuid4())
        doc_ids.append(did)
        db_session.add(
            Document(
                id=did,
                workspace_id=ws.id,
                file_name=name,
                local_path=name,
                content_hash=str(uuid.uuid4()),
                parse_status="done",
                page_count=1,
                created_at=now,
            )
        )
    db_session.commit()

    rid = _make_review(
        db_session,
        ws.id,
        doc_ids,
        [
            (doc_ids[0], "parties", "Google LLC Opposite Party No. 2"),
            (doc_ids[1], "parties", "Informant vs Google India Private Limited"),
            (doc_ids[2], "parties", "Alpha Ltd and Beta Ltd only"),
        ],
    )

    rows = discover_tabular_listing_documents(db_session, rid, match_tokens=["google"])
    found = {d for d, _ in rows}
    assert doc_ids[0] in found
    assert doc_ids[1] in found
    assert doc_ids[2] not in found


def test_unified_discovery_unions_tabular_when_entity_sparse(db_session):
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="CCI", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    doc_ids = [str(uuid.uuid4()) for _ in range(4)]
    for i, did in enumerate(doc_ids):
        db_session.add(
            Document(
                id=did,
                workspace_id=ws.id,
                file_name=f"doc{i}.pdf",
                local_path="x.pdf",
                content_hash=str(uuid.uuid4()),
                parse_status="done",
                page_count=1,
                created_at=now,
            )
        )
    db_session.commit()

    rid = _make_review(
        db_session,
        ws.id,
        doc_ids,
        [(did, "parties", f"Google LLC matter {i}") for i, did in enumerate(doc_ids)],
    )

    understanding = QueryUnderstanding(
        intent="entity_matter_listing",
        target_entity=TargetEntity(
            canonical="google llc",
            surfaces=["Google"],
            resolved_canonicals=["google llc"],
        ),
    )

    with patch(
        "app.services.listing_discovery.lookup_documents_for_party",
        return_value=[(doc_ids[0], 3)],
    ), patch(
        "app.services.listing_discovery.lookup_documents_for_party_tokens",
        return_value=[],
    ), patch(
        "app.services.listing_discovery.discover_documents_from_party_fts",
        return_value=[],
    ):
        doc_rows, diag = discover_listing_documents(
            db_session,
            understanding,
            workspace_id=ws.id,
            document_ids=doc_ids,
            query="list cases against google",
            tabular_review_id=rid,
        )

    assert len(doc_rows) >= 4
    assert diag["documents_total_discovered"] >= 4
    assert diag["discovery_sources"]["tabular"] >= 4


def test_tabular_metadata_block_includes_parties(db_session):
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="W", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    did = str(uuid.uuid4())
    db_session.add(
        Document(
            id=did,
            workspace_id=ws.id,
            file_name="order.pdf",
            local_path="order.pdf",
            content_hash=str(uuid.uuid4()),
            parse_status="done",
            page_count=1,
            created_at=now,
        )
    )
    db_session.commit()
    rid = _make_review(
        db_session,
        ws.id,
        [did],
        [(did, "parties", "Google LLC is Opposite Party No. 2")],
    )
    block = build_tabular_document_metadata_block(db_session, rid, did)
    assert "Google LLC" in block
    assert "Parties" in block
