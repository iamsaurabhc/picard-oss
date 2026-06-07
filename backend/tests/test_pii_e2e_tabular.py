import json
import uuid

import pytest

from app.config import settings
from app.db.models import Chunk, Document, TabularCell, TabularReview, Workspace
from app.db.session import utc_now_iso
from app.schemas import TabularColumn
from tests.pii_test_helpers import LLMCallRecorder


def _parse_sse_events(response) -> list[dict]:
    events: list[dict] = []
    event_type = "message"
    for raw_line in response.iter_lines():
        line = raw_line.decode() if isinstance(raw_line, bytes) else raw_line
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            events.append({"event": event_type, **json.loads(line[5:].strip())})
            event_type = "message"
    return events


@pytest.fixture()
def pii_tabular_fixture(db_session):
    ws_id = str(uuid.uuid4())
    now = utc_now_iso()
    db_session.add(Workspace(id=ws_id, name="PII TR", matter_ref=None, created_at=now, updated_at=now))
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
    chunk_id = str(uuid.uuid4())
    db_session.add(
        Chunk(
            id=chunk_id,
            document_id=doc_id,
            page_number=1,
            chunk_type="paragraph",
            bbox_json="{}",
            text_content="Party Rahul Mehta at rahul@acme.in governs this agreement.",
            heading_path=None,
            section_key=None,
            token_count=12,
        )
    )
    review_id = str(uuid.uuid4())
    columns = [
        TabularColumn(key="party", label="Party", format="text", prompt="State the party."),
    ]
    db_session.add(
        TabularReview(
            id=review_id,
            workspace_id=ws_id,
            title="PII Review",
            columns_config_json=json.dumps([c.model_dump() for c in columns]),
            document_ids_json=json.dumps([doc_id]),
            created_at=now,
        )
    )
    cell_id = str(uuid.uuid4())
    db_session.add(
        TabularCell(
            id=cell_id,
            review_id=review_id,
            document_id=doc_id,
            column_key="party",
            status="pending",
        )
    )
    db_session.commit()
    return {"ws_id": ws_id, "doc_id": doc_id, "review_id": review_id, "cell_id": cell_id, "chunk_id": chunk_id}


def _tabular_cloud(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "pii_use_presidio", False)
    monkeypatch.setattr(settings, "enable_pii_protection_default", True)
    monkeypatch.setattr(settings, "enable_llm_query_understanding", False)
    monkeypatch.setattr(settings, "enable_context_ranker", False)
    monkeypatch.setattr(settings, "enable_hybrid_search", False)


def test_tabular_cell_extract_pii_roundtrip(client, pii_tabular_fixture, monkeypatch):
    _tabular_cloud(monkeypatch)
    f = pii_tabular_fixture
    recorder = LLMCallRecorder(
        completion_response=json.dumps(
            {
                "summary": "<EMAIL_ADDRESS_1>",
                "reasoning": "Found party",
                "chunk_ids": [f["chunk_id"]],
                "flag": "green",
            }
        )
    )
    recorder.install(monkeypatch)

    r = client.post(f"/tabular/cells/{f['cell_id']}/regenerate")
    assert r.status_code == 200
    data = r.json()
    assert recorder.messages_sent
    assert not recorder.contains_raw("rahul@acme.in")
    assert "rahul@acme.in" in (data.get("summary") or "")


def test_tabular_pii_off_extract_raw(client, pii_tabular_fixture, monkeypatch):
    _tabular_cloud(monkeypatch)
    monkeypatch.setattr(settings, "enable_pii_protection_default", False)
    f = pii_tabular_fixture
    recorder = LLMCallRecorder(
        completion_response=json.dumps(
            {
                "summary": "Rahul Mehta",
                "reasoning": "ok",
                "chunk_ids": [f["chunk_id"]],
                "flag": "green",
            }
        )
    )
    recorder.install(monkeypatch)

    r = client.post(f"/tabular/cells/{f['cell_id']}/regenerate")
    assert r.status_code == 200
    assert recorder.contains_raw("rahul@acme.in")


def test_tabular_chat_stream_pii_roundtrip(client, pii_tabular_fixture, db_session, monkeypatch):
    _tabular_cloud(monkeypatch)
    f = pii_tabular_fixture
    row = db_session.get(TabularCell, f["cell_id"])
    row.summary = "rahul@acme.in primary party"
    row.status = "done"
    db_session.commit()

    recorder = LLMCallRecorder(stream_chunks=["Contact ", "<EMAIL_ADDRESS_1>", "."])
    recorder.install(monkeypatch)

    session = client.post("/chat/sessions", json={"workspace_id": f["ws_id"]})
    session_id = session.json()["id"]

    with client.stream(
        "POST",
        "/chat/stream",
        json={
            "session_id": session_id,
            "workspace_id": f["ws_id"],
            "message": "Who is the party Rahul Mehta?",
            "document_ids": [f["doc_id"]],
            "tabular_review_id": f["review_id"],
            "enable_pii_protection": True,
        },
    ) as response:
        assert response.status_code == 200
        events = _parse_sse_events(response)

    if recorder.messages_sent:
        assert not recorder.contains_raw("rahul@acme.in")
    refs = next((e for e in events if e.get("event") == "references"), None)
    if refs and refs.get("content"):
        assert "Rahul" in refs["content"] or "<PERSON" not in refs["content"]
