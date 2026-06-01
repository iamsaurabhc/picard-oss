import uuid

from app.db.models import Chunk, Document, Workspace
from app.db.session import utc_now_iso
from app.services.search import execute_search
from app.schemas import SearchRequest


def test_workspace_isolation(db_session):
    now = utc_now_iso()
    ws1 = Workspace(id=str(uuid.uuid4()), name="W1", matter_ref=None, created_at=now, updated_at=now)
    ws2 = Workspace(id=str(uuid.uuid4()), name="W2", matter_ref=None, created_at=now, updated_at=now)
    db_session.add_all([ws1, ws2])
    doc1 = Document(
        id=str(uuid.uuid4()),
        workspace_id=ws1.id,
        file_name="a.pdf",
        local_path="p/a.pdf",
        content_hash="h1",
        parse_status="done",
        created_at=now,
    )
    db_session.add(doc1)
    db_session.add(
        Chunk(
            id=str(uuid.uuid4()),
            document_id=doc1.id,
            page_number=1,
            chunk_type="paragraph",
            bbox_json='{"x0":0,"y0":0,"x1":1,"y1":1}',
            text_content="unique liability term xyzzy isolation",
            heading_path=None,
            section_key=None,
            token_count=5,
        )
    )
    db_session.commit()

    result = execute_search(
        db_session,
        SearchRequest(query="xyzzy isolation", workspace_id=ws2.id, retrieval_mode="simple"),
    )
    assert result.hits == []
