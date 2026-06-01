import json
import uuid

from app.db.models import Chunk, Document, Workspace
from app.db.session import utc_now_iso


def _seed_document_with_chunks(db_session):
    now = utc_now_iso()
    ws = Workspace(
        id=str(uuid.uuid4()),
        name="Chunks Test",
        matter_ref=None,
        created_at=now,
        updated_at=now,
    )
    doc_id = str(uuid.uuid4())
    doc = Document(
        id=doc_id,
        workspace_id=ws.id,
        file_name="sample.pdf",
        local_path=f"pdfs/{ws.id}/{doc_id}.pdf",
        content_hash="abc123",
        page_count=2,
        parse_status="done",
        created_at=now,
    )
    db_session.add(ws)
    db_session.add(doc)

    chunks = [
        Chunk(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            page_number=1,
            chunk_type="heading",
            bbox_json=json.dumps({"x0": 0.1, "y0": 0.2, "x1": 0.9, "y1": 0.25}),
            text_content="Section 1",
            heading_path="Section 1",
            section_key="sec1",
            token_count=2,
        ),
        Chunk(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            page_number=1,
            chunk_type="paragraph",
            bbox_json=json.dumps({"x0": 0.1, "y0": 0.3, "x1": 0.9, "y1": 0.5}),
            text_content="Body text on page one.",
            heading_path="Section 1",
            section_key="sec1",
            token_count=5,
        ),
        Chunk(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            page_number=2,
            chunk_type="paragraph",
            bbox_json=json.dumps({"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.3}),
            text_content="Page two content.",
            heading_path=None,
            section_key=None,
            token_count=3,
        ),
    ]
    db_session.add_all(chunks)
    db_session.commit()
    return doc_id, chunks


def test_list_chunks_returns_all_sorted(client, db_session):
    doc_id, chunks = _seed_document_with_chunks(db_session)

    r = client.get(f"/documents/{doc_id}/chunks")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 3
    assert data[0]["chunk_type"] == "heading"
    assert data[0]["bbox"]["y0"] == 0.2
    assert data[1]["page_number"] == 1
    assert data[1]["bbox"]["y0"] == 0.3
    assert data[2]["page_number"] == 2


def test_list_chunks_page_filter(client, db_session):
    doc_id, _ = _seed_document_with_chunks(db_session)

    r = client.get(f"/documents/{doc_id}/chunks", params={"page": 1})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert all(c["page_number"] == 1 for c in data)
    assert data[0]["text_content"] == "Section 1"
    assert data[1]["text_content"] == "Body text on page one."


def test_list_chunks_not_found(client):
    r = client.get(f"/documents/{uuid.uuid4()}/chunks")
    assert r.status_code == 404


def test_list_chunks_empty_for_pending_doc(client, db_session):
    now = utc_now_iso()
    ws = Workspace(
        id=str(uuid.uuid4()),
        name="Pending",
        matter_ref=None,
        created_at=now,
        updated_at=now,
    )
    doc_id = str(uuid.uuid4())
    doc = Document(
        id=doc_id,
        workspace_id=ws.id,
        file_name="pending.pdf",
        local_path=f"pdfs/{ws.id}/{doc_id}.pdf",
        content_hash="pending",
        parse_status="pending",
        created_at=now,
    )
    db_session.add(ws)
    db_session.add(doc)
    db_session.commit()

    r = client.get(f"/documents/{doc_id}/chunks")
    assert r.status_code == 200
    assert r.json() == []
