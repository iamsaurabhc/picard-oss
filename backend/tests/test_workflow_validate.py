"""Phase 6 workflow library tests (WF-02, WF-04, WF-05)."""

from __future__ import annotations

import json

import pytest

from app.db.models import Workflow
from app.db.session import utc_now_iso
from app.services.workflows_store import list_workflows, seed_builtin_workflows, workflow_matches_profile
from app.workflows.builtins import builtin_workflow_defs
from app.workflows.validate import validate_workflow_record


def test_builtin_defs_validate():
    for row in builtin_workflow_defs():
        result = validate_workflow_record(
            flow_json=row["flow_json"],
            evidence_profile_json=row["evidence_profile_json"],
        )
        assert result.valid, (row["id"], result.errors)


def test_invalid_cycle_fails():
    flow = {
        "version": "0.8",
        "steps": [
            {"name": "a", "role": "research", "depends_on": ["b"]},
            {"name": "b", "role": "research", "depends_on": ["a"]},
        ],
    }
    profile = {"requires_corpus": True, "allows_web": False}
    result = validate_workflow_record(flow_json=flow, evidence_profile_json=profile)
    assert not result.valid
    assert any(i.code == "dag" for i in result.errors)


def test_denied_role_fails():
    flow = {
        "version": "0.8",
        "steps": [{"name": "fetch", "role": "web"}],
    }
    profile = {
        "requires_corpus": True,
        "allows_web": False,
        "denied_roles": ["web"],
    }
    result = validate_workflow_record(flow_json=flow, evidence_profile_json=profile)
    assert not result.valid


def test_profile_filter_wf04():
    assert workflow_matches_profile("any", "firm")
    assert workflow_matches_profile("any", "court")
    assert workflow_matches_profile("firm", "firm")
    assert not workflow_matches_profile("firm", "court")
    assert not workflow_matches_profile("court", "firm")


def test_list_workflows_hides_firm_only_for_court(client, db_session, monkeypatch):
    from app.config import settings

    seed_builtin_workflows(db_session)
    db_session.commit()
    monkeypatch.setattr(settings, "agent_profile", "court")

    rows = list_workflows(db_session, agent_profile="court")
    ids = {r["id"] for r in rows}
    assert "builtin:dd-memo" not in ids
    assert "builtin:court-filing-defect" in ids


def test_tabular_workflow_columns_wf02(client, db_session):
    seed_builtin_workflows(db_session)
    db_session.commit()
    wf = db_session.get(Workflow, "builtin:tabular-contract")
    assert wf is not None
    cols = json.loads(wf.columns_config_json or "[]")
    keys = {c["key"] for c in cols}
    assert "parties" in keys
    assert "governing_law" in keys


def test_workflows_api_list(client, db_session):
    seed_builtin_workflows(db_session)
    db_session.commit()
    r = client.get("/workflows")
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 15


def test_workflow_intent_hint_single(client, db_session):
    from app.services.workflows_store import get_workflow_intent_hint

    seed_builtin_workflows(db_session)
    db_session.commit()
    wf = db_session.get(Workflow, "builtin:matter-overview")
    assert get_workflow_intent_hint(wf) == "case_overview"
