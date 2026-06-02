import json
import uuid

import pytest

from app.db.models import Document, TabularCell, TabularReview, Workspace
from app.db.session import utc_now_iso


@pytest.fixture()
def tabular_fixture(db_session):
    ws_id = str(uuid.uuid4())
    now = utc_now_iso()
    db_session.add(Workspace(id=ws_id, name="TR Test", matter_ref=None, created_at=now, updated_at=now))
    db_session.flush()
    doc_id = str(uuid.uuid4())
    db_session.add(
        Document(
            id=doc_id,
            workspace_id=ws_id,
            file_name="contract.pdf",
            local_path="/tmp/contract.pdf",
            parse_status="done",
            created_at=now,
        )
    )
    db_session.flush()
    review_id = str(uuid.uuid4())
    db_session.add(
        TabularReview(
            id=review_id,
            workspace_id=ws_id,
            title="Pilot",
            columns_config_json=json.dumps(
                [{"key": "term", "label": "Term", "format": "text", "prompt": "State the term."}]
            ),
            document_ids_json=json.dumps([doc_id]),
            created_at=now,
        )
    )
    db_session.add(
        TabularCell(
            id=str(uuid.uuid4()),
            review_id=review_id,
            document_id=doc_id,
            column_key="term",
            status="pending",
        )
    )
    db_session.commit()
    return {"ws_id": ws_id, "doc_id": doc_id, "review_id": review_id}


def test_delete_review(client, tabular_fixture):
    f = tabular_fixture
    review_id = f["review_id"]

    r = client.delete(f"/tabular/reviews/{review_id}")
    assert r.status_code == 204

    r2 = client.get(f"/tabular/reviews/{review_id}")
    assert r2.status_code == 404
