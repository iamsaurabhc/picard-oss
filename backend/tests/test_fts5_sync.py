import json
import uuid

from sqlalchemy import text

from app.db.models import Chunk, Document, Workspace
from app.db.session import utc_now_iso


def test_fts5_sync_on_insert(db_session):
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="Test", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    doc = Document(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        file_name="a.pdf",
        local_path="pdfs/x/a.pdf",
        content_hash="abc",
        parse_status="done",
        created_at=now,
    )
    db_session.add(doc)
    db_session.flush()
    chunk = Chunk(
        id=str(uuid.uuid4()),
        document_id=doc.id,
        page_number=1,
        chunk_type="paragraph",
        bbox_json=json.dumps({"x0": 0, "y0": 0, "x1": 1, "y1": 1}),
        text_content="This agreement contains confidentiality obligations.",
        heading_path=None,
        section_key=None,
        token_count=5,
    )
    db_session.add(chunk)
    db_session.commit()

    row = db_session.execute(
        text("SELECT COUNT(*) AS c FROM chunks_fts WHERE chunks_fts MATCH 'confidentiality'")
    ).scalar_one()
    assert row == 1
