import json
import uuid

import pytest

from app.config import settings
from app.db.session import utc_now_iso
from tests.corpus_constants import WORKSPACE_ID


def _parse_sse_events(response) -> list[dict]:
    events: list[dict] = []
    event_type = "message"
    for raw_line in response.iter_lines():
        if isinstance(raw_line, bytes):
            line = raw_line.decode()
        else:
            line = raw_line
        if line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            payload = json.loads(line[5:].strip())
            events.append({"event": event_type, **payload})
            event_type = "message"
    return events


@pytest.fixture()
def chat_session(client, db_session):
    from app.db.models import Workspace

    ws_id = str(uuid.uuid4())
    now = utc_now_iso()
    db_session.add(Workspace(id=ws_id, name="Chat Test", matter_ref=None, created_at=now, updated_at=now))
    db_session.commit()
    r = client.post("/chat/sessions", json={"workspace_id": ws_id, "title": "Assistant"})
    assert r.status_code == 200
    return r.json()["id"], ws_id


def test_create_session_and_messages(client, chat_session):
    session_id, _ws = chat_session
    r = client.get(f"/chat/sessions/{session_id}/messages")
    assert r.status_code == 200
    assert r.json() == []

    detail = client.get(f"/chat/sessions/{session_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == session_id
    assert body["updated_at"]
    assert body["document_ids"] == []


def test_list_sessions_ordered_by_activity(client, chat_session, monkeypatch):
    session_id, ws_id = chat_session
    older = client.post(
        "/chat/sessions",
        json={"workspace_id": ws_id, "title": "older", "reuse_draft": False},
    )
    assert older.status_code == 200
    older_id = older.json()["id"]

    async def fake_stream(*args, **kwargs):
        yield "Hi."

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)
    monkeypatch.setattr(settings, "enable_llm_query_understanding", False)
    monkeypatch.setattr(settings, "enable_context_ranker", False)

    with client.stream(
        "POST",
        "/chat/stream",
        json={
            "session_id": session_id,
            "workspace_id": ws_id,
            "message": "ping",
            "retrieval_mode": "simple",
        },
    ) as response:
        assert response.status_code == 200
        for _ in response.iter_lines():
            pass

    with client.stream(
        "POST",
        "/chat/stream",
        json={
            "session_id": older_id,
            "workspace_id": ws_id,
            "message": "pong",
            "retrieval_mode": "simple",
        },
    ) as response:
        assert response.status_code == 200
        for _ in response.iter_lines():
            pass

    r = client.get(f"/workspaces/{ws_id}/chat/sessions")
    assert r.status_code == 200
    sessions = r.json()
    assert len(sessions) >= 2
    ids = [s["id"] for s in sessions]
    assert session_id in ids
    assert older_id in ids
    assert older_id != session_id
    assert sessions[0]["updated_at"] >= sessions[1]["updated_at"]


def test_delete_session(client, chat_session):
    session_id, ws_id = chat_session
    r = client.delete(f"/chat/sessions/{session_id}")
    assert r.status_code == 204
    assert client.get(f"/chat/sessions/{session_id}").status_code == 404
    listed = client.get(f"/workspaces/{ws_id}/chat/sessions").json()
    assert session_id not in [s["id"] for s in listed]


@pytest.mark.corpus
def test_ab01_refuse_no_llm_tokens(corpus_client, monkeypatch):
    """Zero-evidence CARP query should refuse without calling stream_completion."""
    called = {"stream": False}

    async def fake_stream(*args, **kwargs):
        called["stream"] = True
        yield "should not run"

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)
    monkeypatch.setattr(settings, "enable_llm_query_understanding", False)
    monkeypatch.setattr(settings, "enable_context_ranker", False)

    session_r = corpus_client.post("/chat/sessions", json={"workspace_id": WORKSPACE_ID})
    session_id = session_r.json()["id"]

    with corpus_client.stream(
        "POST",
        "/chat/stream",
        json={
            "session_id": session_id,
            "workspace_id": WORKSPACE_ID,
            "message": "case context for janet chester and agreement that",
            "retrieval_mode": "multi_constraint",
        },
    ) as response:
        assert response.status_code == 200
        payloads = []
        for line in response.iter_lines():
            if line.startswith("data:"):
                payloads.append(json.loads(line[5:].strip()))

    assert not called["stream"]
    assert any(p.get("refused") for p in payloads)


def test_chat_stream_mock_llm(client, chat_session, monkeypatch):
    session_id, ws_id = chat_session

    async def fake_stream(*args, **kwargs):
        yield "Answer [1]."

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)
    monkeypatch.setattr(settings, "enable_llm_query_understanding", False)
    monkeypatch.setattr(settings, "enable_context_ranker", False)

    with client.stream(
        "POST",
        "/chat/stream",
        json={
            "session_id": session_id,
            "workspace_id": ws_id,
            "message": "liability",
            "retrieval_mode": "simple",
        },
    ) as response:
        assert response.status_code == 200
        events = _parse_sse_events(response)
        event_types = [e["event"] for e in events]
        assert event_types[0] == "progress"
        assert events[0]["phase"] == "understanding"
        assert events[0]["status"] == "start"
        assert "retrieval" in event_types
        assert "content" in event_types
        progress_before_retrieval = event_types.index("retrieval") > event_types.index(
            next(e for e in event_types if e == "progress")
        )
        assert progress_before_retrieval


@pytest.mark.corpus
def test_chat_stream_progress_snippets(corpus_client, monkeypatch):
    async def fake_stream(*args, **kwargs):
        yield "Answer [1]."

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)
    monkeypatch.setattr(settings, "enable_llm_query_understanding", False)
    monkeypatch.setattr(settings, "enable_context_ranker", False)

    session_r = corpus_client.post("/chat/sessions", json={"workspace_id": WORKSPACE_ID})
    session_id = session_r.json()["id"]

    with corpus_client.stream(
        "POST",
        "/chat/stream",
        json={
            "session_id": session_id,
            "workspace_id": WORKSPACE_ID,
            "message": "liability",
            "retrieval_mode": "simple",
        },
    ) as response:
        assert response.status_code == 200
        events = _parse_sse_events(response)

    assert events[0]["event"] == "progress"
    assert events[0]["phase"] == "understanding"
    retrieval_idx = next(i for i, e in enumerate(events) if e["event"] == "retrieval")
    assert any(e["event"] == "progress" for e in events[:retrieval_idx])

    snippets = [e for e in events if e["event"] == "snippet"]
    assert snippets, "expected at least one snippet event on corpus liability query"
    first = snippets[0]
    assert first["text"]
    assert first["document_name"]
    assert first["page_number"] >= 1


def test_reuse_draft_session(client, chat_session):
    _fixture_id, ws_id = chat_session
    first = client.post(
        "/chat/sessions",
        json={"workspace_id": ws_id, "reuse_draft": True},
    )
    second = client.post(
        "/chat/sessions",
        json={"workspace_id": ws_id, "reuse_draft": True},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    listed = client.get(f"/workspaces/{ws_id}/chat/sessions").json()
    assert listed == []


def test_list_sessions_after_user_message(client, chat_session, monkeypatch):
    session_id, ws_id = chat_session

    async def fake_stream(*args, **kwargs):
        yield "Answer."

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)
    monkeypatch.setattr(settings, "enable_llm_query_understanding", False)
    monkeypatch.setattr(settings, "enable_context_ranker", False)

    with client.stream(
        "POST",
        "/chat/stream",
        json={
            "session_id": session_id,
            "workspace_id": ws_id,
            "message": "hello",
            "retrieval_mode": "simple",
        },
    ) as response:
        assert response.status_code == 200
        for _ in response.iter_lines():
            pass

    listed = client.get(f"/workspaces/{ws_id}/chat/sessions").json()
    assert len(listed) == 1
    assert listed[0]["has_user_message"] is True
    assert listed[0]["preview"]


def test_stream_persists_document_scope_and_autotitle(client, chat_session, monkeypatch):
    _fixture_id, ws_id = chat_session
    created = client.post(
        "/chat/sessions",
        json={"workspace_id": ws_id, "title": "New chat", "reuse_draft": False},
    )
    assert created.status_code == 200
    session_id = created.json()["id"]
    assert session_id != _fixture_id
    doc_ids = ["doc-a", "doc-b"]

    async def fake_stream(*args, **kwargs):
        yield "Answer [1]."

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)
    monkeypatch.setattr(settings, "enable_llm_query_understanding", False)
    monkeypatch.setattr(settings, "enable_context_ranker", False)

    with client.stream(
        "POST",
        "/chat/stream",
        json={
            "session_id": session_id,
            "workspace_id": ws_id,
            "message": "What is the indemnity cap?",
            "document_ids": doc_ids,
            "retrieval_mode": "simple",
        },
    ) as response:
        assert response.status_code == 200
        for _ in response.iter_lines():
            pass

    detail = client.get(f"/chat/sessions/{session_id}").json()
    assert detail["document_ids"] == doc_ids
    assert "indemnity" in (detail["title"] or "").lower()

    listed = client.get(f"/workspaces/{ws_id}/chat/sessions").json()
    row = next(s for s in listed if s["id"] == session_id)
    assert row["message_count"] >= 2
    assert row["preview"]


def test_messages_include_references_after_stream(client, chat_session, monkeypatch):
    session_id, ws_id = chat_session

    async def fake_stream(*args, **kwargs):
        yield "Answer [1]."

    monkeypatch.setattr("app.services.chat.stream_completion", fake_stream)
    monkeypatch.setattr(settings, "enable_llm_query_understanding", False)
    monkeypatch.setattr(settings, "enable_context_ranker", False)

    with client.stream(
        "POST",
        "/chat/stream",
        json={
            "session_id": session_id,
            "workspace_id": ws_id,
            "message": "liability",
            "retrieval_mode": "simple",
        },
    ) as response:
        assert response.status_code == 200
        for _ in response.iter_lines():
            pass

    messages = client.get(f"/chat/sessions/{session_id}/messages").json()
    assistant = [m for m in messages if m["role"] == "assistant"]
    assert assistant
    assert assistant[-1]["content"]
