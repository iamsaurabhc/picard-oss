import json
import uuid

import pytest

from app.config import settings
from app.db.models import Chunk, Document, Workspace
from app.db.session import utc_now_iso
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
def pii_chat_fixture(db_session):
    ws_id = str(uuid.uuid4())
    now = utc_now_iso()
    db_session.add(Workspace(id=ws_id, name="PII", matter_ref=None, created_at=now, updated_at=now))
    doc_id = str(uuid.uuid4())
    db_session.add(
        Document(
            id=doc_id,
            workspace_id=ws_id,
            file_name="nda.pdf",
            local_path="/tmp/nda.pdf",
            parse_status="done",
            created_at=now,
        )
    )
    chunk_id = str(uuid.uuid4())
    db_session.add(
        Chunk(
            id=chunk_id,
            document_id=doc_id,
            page_number=1,
            chunk_type="paragraph",
            bbox_json="{}",
            text_content="Rahul Mehta agrees to liability caps. Contact rahul@acme.in or +919876543210.",
            heading_path=None,
            section_key=None,
            token_count=20,
        )
    )
    db_session.commit()
    return {"ws_id": ws_id, "doc_id": doc_id}


def _pii_cloud_settings(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "pii_use_presidio", False)
    monkeypatch.setattr(settings, "enable_llm_query_understanding", False)
    monkeypatch.setattr(settings, "enable_context_ranker", False)
    monkeypatch.setattr(settings, "enable_hybrid_search", False)


def test_chat_pii_on_masks_cloud_llm(client, pii_chat_fixture, monkeypatch):
    _pii_cloud_settings(monkeypatch)
    monkeypatch.setattr(settings, "chat_latency_profile", "balanced")
    f = pii_chat_fixture
    recorder = LLMCallRecorder(
        stream_chunks=["Contact ", "<EMAIL_ADDRESS_1>", " for liability."]
    )
    recorder.install(monkeypatch)

    session = client.post("/chat/sessions", json={"workspace_id": f["ws_id"]})
    session_id = session.json()["id"]

    with client.stream(
        "POST",
        "/chat/stream",
        json={
            "session_id": session_id,
            "workspace_id": f["ws_id"],
            "message": "liability Rahul Mehta rahul@acme.in",
            "document_ids": [f["doc_id"]],
            "retrieval_mode": "simple",
            "enable_pii_protection": True,
        },
    ) as response:
        assert response.status_code == 200
        events = _parse_sse_events(response)

    assert recorder.messages_sent
    assert not recorder.contains_raw("rahul@acme.in")
    content_events = "".join(e.get("delta", "") for e in events if e.get("event") == "content")
    refs = next((e for e in events if e.get("event") == "references"), None)
    final_text = (refs or {}).get("content") or content_events
    assert "rahul@acme.in" in final_text

    msgs = client.get(f"/chat/sessions/{session_id}/messages").json()
    assistant = [m for m in msgs if m["role"] == "assistant"][-1]
    assert "rahul@acme.in" in assistant["content"]


def test_chat_pii_off_sends_raw(client, pii_chat_fixture, monkeypatch):
    _pii_cloud_settings(monkeypatch)
    f = pii_chat_fixture
    recorder = LLMCallRecorder(stream_chunks=["ok"])
    recorder.install(monkeypatch)

    session = client.post("/chat/sessions", json={"workspace_id": f["ws_id"]})
    session_id = session.json()["id"]

    with client.stream(
        "POST",
        "/chat/stream",
        json={
            "session_id": session_id,
            "workspace_id": f["ws_id"],
            "message": "liability Rahul Mehta rahul@acme.in",
            "document_ids": [f["doc_id"]],
            "retrieval_mode": "simple",
            "enable_pii_protection": False,
        },
    ) as response:
        assert response.status_code == 200
        for _ in response.iter_lines():
            pass

    assert recorder.contains_raw("Rahul Mehta") or recorder.contains_raw("rahul@acme.in")


def test_chat_pii_ollama_bypass(client, pii_chat_fixture, monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(settings, "enable_llm_query_understanding", False)
    monkeypatch.setattr(settings, "enable_context_ranker", False)
    monkeypatch.setattr(settings, "enable_hybrid_search", False)
    f = pii_chat_fixture
    recorder = LLMCallRecorder(stream_chunks=["Rahul Mehta raw"])
    recorder.install(monkeypatch)

    session = client.post("/chat/sessions", json={"workspace_id": f["ws_id"]})
    session_id = session.json()["id"]

    with client.stream(
        "POST",
        "/chat/stream",
        json={
            "session_id": session_id,
            "workspace_id": f["ws_id"],
            "message": "liability Rahul Mehta",
            "document_ids": [f["doc_id"]],
            "enable_pii_protection": True,
        },
    ) as response:
        assert response.status_code == 200
        for _ in response.iter_lines():
            pass

    if recorder.messages_sent:
        assert recorder.contains_raw("Rahul Mehta") or "Rahul" in recorder.all_message_text()
