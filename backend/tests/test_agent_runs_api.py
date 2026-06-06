"""Agent runs API (Phase 7a)."""

from app.db.models import AgentRun, Workspace
from app.db.session import utc_now_iso


def test_get_agent_run(client, db_session):
    ws = db_session.get(Workspace, "ws-agent")
    if not ws:
        ws = Workspace(
            id="ws-agent",
            name="Test",
            matter_ref=None,
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
        )
        db_session.add(ws)
        db_session.commit()
    run = AgentRun(
        id="run-1",
        session_id=None,
        workspace_id="ws-agent",
        profile="firm",
        mode="agent",
        plan_json=None,
        events_json='[{"event":"memory_hit","memories":["DD review order"]}]',
        status="completed",
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
    )
    db_session.add(run)
    db_session.commit()

    res = client.get("/agent/runs/run-1")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == "run-1"
    assert len(data["events"]) == 1
