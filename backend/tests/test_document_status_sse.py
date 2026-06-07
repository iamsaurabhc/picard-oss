import json
import uuid

from app.db.models import Document
from app.db.session import utc_now_iso


def _create_workspace(client):
    r = client.post("/workspaces", json={"name": "SSE Test"})
    assert r.status_code in (200, 201)
    return r.json()["id"]


def _parse_sse_events(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event_type = "message"
    for line in text.splitlines():
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data = json.loads(line[5:].strip())
            events.append((event_type, data))
    return events


def test_document_status_stream_not_found(client):
    r = client.get(f"/documents/{uuid.uuid4()}/status/stream")
    assert r.status_code == 404


def test_document_status_stream_ready(client, db_session, test_sessionmaker, monkeypatch):
    monkeypatch.setattr("app.routers.document_status_sse.SessionLocal", test_sessionmaker)
    ws_id = _create_workspace(client)
    now = utc_now_iso()
    doc_id = str(uuid.uuid4())
    doc = Document(
        id=doc_id,
        workspace_id=ws_id,
        file_name="test.pdf",
        local_path="pdfs/x/test.pdf",
        parse_status="done",
        page_count=5,
        created_at=now,
    )
    db_session.add(doc)
    db_session.commit()

    with client.stream("GET", f"/documents/{doc_id}/status/stream") as resp:
        assert resp.status_code == 200
        body = resp.read().decode()
        events = _parse_sse_events(body)
        event_names = [e[0] for e in events]
        assert "status" in event_names
        assert "ready" in event_names
        ready = next(e[1] for e in events if e[0] == "ready")
        assert ready["page_count"] == 5


def test_document_status_stream_error(client, db_session, test_sessionmaker, monkeypatch):
    monkeypatch.setattr("app.routers.document_status_sse.SessionLocal", test_sessionmaker)
    ws_id = _create_workspace(client)
    now = utc_now_iso()
    doc_id = str(uuid.uuid4())
    doc = Document(
        id=doc_id,
        workspace_id=ws_id,
        file_name="bad.pdf",
        local_path="pdfs/x/bad.pdf",
        parse_status="error",
        parse_error="Corrupt PDF",
        created_at=now,
    )
    db_session.add(doc)
    db_session.commit()

    with client.stream("GET", f"/documents/{doc_id}/status/stream") as resp:
        assert resp.status_code == 200
        body = resp.read().decode()
        events = _parse_sse_events(body)
        assert any(e[0] == "error" for e in events)
        err = next(e[1] for e in events if e[0] == "error")
        assert "Corrupt" in err["detail"]
