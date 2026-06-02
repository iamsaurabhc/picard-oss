import json
import uuid

from app.db.models import Chunk, Document, Entity, EntityMention, MetadataTag, TabularReview, Workspace
from app.db.session import utc_now_iso


def test_workspace_overview(client, db_session):
    ws_id = str(uuid.uuid4())
    now = utc_now_iso()
    db_session.add(Workspace(id=ws_id, name="Overview WS", matter_ref="CM-1", created_at=now, updated_at=now))
    db_session.flush()

    doc_id = str(uuid.uuid4())
    db_session.add(
        Document(
            id=doc_id,
            workspace_id=ws_id,
            file_name="order.pdf",
            local_path="/tmp/order.pdf",
            parse_status="done",
            created_at=now,
        )
    )
    db_session.flush()
    chunk_id = str(uuid.uuid4())
    db_session.add(
        Chunk(
            id=chunk_id,
            document_id=doc_id,
            page_number=1,
            chunk_type="paragraph",
            bbox_json="{}",
            text_content="Google LLC is a party.",
            heading_path=None,
            section_key=None,
            token_count=5,
        )
    )
    db_session.flush()
    db_session.add(
        MetadataTag(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            tag_key="doc_type",
            tag_value="regulatory",
            source_chunk_id=chunk_id,
        )
    )
    eid = str(uuid.uuid4())
    db_session.add(
        Entity(
            id=eid,
            workspace_id=ws_id,
            entity_type="party",
            canonical_value="google",
            display_value="Google LLC",
        )
    )
    db_session.flush()
    db_session.add(
        EntityMention(
            id=str(uuid.uuid4()),
            entity_id=eid,
            document_id=doc_id,
            chunk_id=chunk_id,
            page_number=1,
            char_start=None,
            char_end=None,
            surface_text="Google LLC",
            confidence=1.0,
            source="rule",
        )
    )
    db_session.add(
        TabularReview(
            id=str(uuid.uuid4()),
            workspace_id=ws_id,
            title="Review",
            columns_config_json=json.dumps(
                [{"key": "term", "label": "Term", "format": "text", "prompt": "x"}]
            ),
            document_ids_json=json.dumps([doc_id]),
            created_at=now,
        )
    )
    db_session.commit()

    r = client.get(f"/workspaces/{ws_id}/overview")
    assert r.status_code == 200
    data = r.json()
    assert data["workspace"]["name"] == "Overview WS"
    assert data["documents"]["total"] == 1
    assert data["documents"]["done"] == 1
    assert data["tabular_reviews"] == 1
    assert len(data["parties"]) >= 1
    assert data["parties"][0]["display_value"] == "Google LLC"
    assert any(d["doc_type"] == "regulatory" for d in data["doc_types"])
