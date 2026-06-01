import json
import uuid

from app.db.models import Chunk, Document, Entity, PageEntity, Workspace
from app.db.session import utc_now_iso
from app.services.entity_index import extract_entities_for_document, normalize_date


def test_normalize_date():
    assert normalize_date("18/05/2019") == "2019-05-18"


def test_entity_extract_condition_and_date(db_session):
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="Test", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    doc = Document(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        file_name="multi.pdf",
        local_path="pdfs/x/multi.pdf",
        content_hash="hash",
        parse_status="done",
        created_at=now,
    )
    db_session.add(doc)
    db_session.flush()

    heading = Chunk(
        id=str(uuid.uuid4()),
        document_id=doc.id,
        page_number=1,
        chunk_type="heading",
        bbox_json=json.dumps({"x0": 0, "y0": 0, "x1": 1, "y1": 0.1}),
        text_content="Condition C — Warranties",
        heading_path="Condition C — Warranties",
        section_key="sec1",
        token_count=3,
    )
    body = Chunk(
        id=str(uuid.uuid4()),
        document_id=doc.id,
        page_number=1,
        chunk_type="paragraph",
        bbox_json=json.dumps({"x0": 0, "y0": 0.2, "x1": 1, "y1": 0.4}),
        text_content="Party ABC agreed on 18/05/2019 to the terms herein.",
        heading_path="Condition C — Warranties",
        section_key="sec1",
        token_count=10,
    )
    db_session.add_all([heading, body])
    db_session.commit()

    count = extract_entities_for_document(db_session, doc.id)
    assert count > 0

    entities = db_session.query(Entity).filter(Entity.workspace_id == ws.id).all()
    types = {e.entity_type for e in entities}
    assert "date" in types
    assert "condition" in types

    pe_count = db_session.query(PageEntity).filter(PageEntity.document_id == doc.id).count()
    assert pe_count >= 2
