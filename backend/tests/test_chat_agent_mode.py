"""Chat stream agent mode gate (Phase 7a)."""

from app.config import settings


def test_agent_mode_disabled_returns_403(client):
    settings.enable_agent_mode = False
    res = client.post(
        "/chat/stream",
        json={
            "session_id": "x",
            "workspace_id": "y",
            "message": "hello",
            "mode": "agent",
        },
    )
    assert res.status_code == 403
