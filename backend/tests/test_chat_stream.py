import json
import uuid

import pytest

from app.config import settings
from app.db.session import utc_now_iso
from tests.corpus_constants import WORKSPACE_ID


@pytest.fixture()
def chat_session(client, db_session):
    from app.db.models import Workspace

    ws_id = str(uuid.uuid4())
    now = utc_now_iso()
    db_session.add(Workspace(id=ws_id, name="Chat Test", matter_ref=None, created_at=now, updated_at=now))
    db_session.commit()
    r = client.post("/chat/sessions", json={"workspace_id": ws_id, "title": "test"})
    assert r.status_code == 200
    return r.json()["id"], ws_id


def test_create_session_and_messages(client, chat_session):
    session_id, _ws = chat_session
    r = client.get(f"/chat/sessions/{session_id}/messages")
    assert r.status_code == 200
    assert r.json() == []


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
        content = "".join(response.iter_lines())
        assert "retrieval" in content or "content" in content
