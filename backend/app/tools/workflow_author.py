from __future__ import annotations

import json
from app.services.agent_hitl import create_approval, plan_hitl_required
from app.services.workflows_store import (
    create_workflow,
    export_workflow,
    list_workflows,
    validate_payload,
)
from app.workflows.schema import EvidenceProfile, FlowJson, WorkflowPayload
from app.tools.context import ToolContext
from app.tools.response import tool_json


def _inventory_summary(ctx: ToolContext) -> dict:
    from sqlalchemy import func, select

    from app.db.models import Document, TabularReview

    doc_count = ctx.db.scalar(
        select(func.count()).select_from(Document).where(Document.workspace_id == ctx.workspace_id)
    )
    tab_count = ctx.db.scalar(
        select(func.count()).select_from(TabularReview).where(TabularReview.workspace_id == ctx.workspace_id)
    )
    wfs = list_workflows(ctx.db, workspace_id=ctx.workspace_id, agent_profile=ctx.profile)
    return {
        "document_count": doc_count or 0,
        "tabular_review_count": tab_count or 0,
        "workflow_count": len(wfs),
    }


def bind_workflow_tools(ctx: ToolContext) -> list:
    tools = []

    def list_workflows_tool() -> str:
        rows = list_workflows(ctx.db, workspace_id=ctx.workspace_id, agent_profile=ctx.profile)
        data = [{"id": w["id"], "title": w["title"], "type": w["type"]} for w in rows]
        return tool_json(refused=False, content=json.dumps(data))

    list_workflows_tool.tool_info = {
        "name": "list_workflows",
        "description": "List workflows available in workspace.",
    }
    tools.append(list_workflows_tool)

    def read_workflow(workflow_id: str) -> str:
        data = export_workflow(ctx.db, workflow_id)
        return tool_json(refused=False, content=json.dumps(data))

    read_workflow.tool_info = {
        "name": "read_workflow",
        "description": "Read workflow detail including flow_json.",
    }
    tools.append(read_workflow)

    def validate_flow(flow_json_str: str) -> str:
        try:
            flow_data = json.loads(flow_json_str)
        except json.JSONDecodeError as exc:
            return tool_json(refused=True, error=str(exc))
        flow = FlowJson.model_validate(flow_data)
        profile = EvidenceProfile(requires_corpus=True, allows_tabular=True)
        payload = WorkflowPayload(
            workspace_id=ctx.workspace_id,
            type="lightflow",
            title="draft",
            flow_json=flow,
            evidence_profile=profile,
        )
        result = validate_payload(payload)
        return tool_json(
            refused=not result.valid,
            content=json.dumps({"valid": result.valid, "errors": [e.model_dump() for e in result.errors]}),
        )

    validate_flow.tool_info = {
        "name": "validate_flow",
        "description": "Lint flow_json against Picard schema.",
    }
    tools.append(validate_flow)

    def propose_flow(goal: str) -> str:
        inv = _inventory_summary(ctx)
        steps = []
        if inv["document_count"] > 0:
            steps.append(
                {
                    "name": "research",
                    "role": "research",
                    "refuse_on_empty": True,
                    "query": {"template": "{{input.question}}"},
                }
            )
        if inv["tabular_review_count"] > 0:
            steps.insert(
                0,
                {"name": "tabular_read", "role": "tabular", "depends_on": [], "config": {"action": "read_cells"}},
            )
        if not steps:
            steps.append(
                {
                    "name": "ingest_check",
                    "role": "research",
                    "config": {"action": "wait_parse"},
                }
            )
        flow = {
            "version": "0.8",
            "input_hint": goal[:200],
            "steps": steps,
        }
        ctx.pending_plan_json = flow
        ctx.emit({"event": "workflow_draft", "flow_json": flow, "goal": goal})
        if plan_hitl_required(ctx.profile):
            token = create_approval(
                session_id=ctx.session_id,
                kind="plan",
                payload={"flow_json": flow},
            )
            ctx.emit({"event": "approval_required", "kind": "plan", "token": token, "flow_json": flow})
        return tool_json(refused=False, content=json.dumps(flow), flow_json=flow)

    propose_flow.tool_info = {
        "name": "propose_flow",
        "description": "Draft flow_json DAG from workspace inventory and user goal.",
    }
    tools.append(propose_flow)

    def save_flow(title: str, flow_json_str: str, workflow_type: str = "lightflow") -> str:
        if plan_hitl_required(ctx.profile) and not ctx.plan_approved and ctx.pending_plan_json:
            return tool_json(refused=True, error="HITL-PLAN: approve workflow draft before save.")
        try:
            flow_data = json.loads(flow_json_str)
        except json.JSONDecodeError as exc:
            return tool_json(refused=True, error=str(exc))
        flow = FlowJson.model_validate(flow_data)
        profile = EvidenceProfile(requires_corpus=True, allows_tabular=True)
        payload = WorkflowPayload(
            workspace_id=ctx.workspace_id,
            type=workflow_type,  # type: ignore[arg-type]
            title=title,
            flow_json=flow,
            evidence_profile=profile,
            profile=ctx.profile if ctx.profile in {"firm", "court"} else "any",  # type: ignore[arg-type]
        )
        validation = validate_payload(payload)
        if not validation.valid:
            return tool_json(
                refused=True,
                content=json.dumps({"errors": [e.model_dump() for e in validation.errors]}),
            )
        wf = create_workflow(ctx.db, payload, source="agent_authored")
        ctx.emit({"event": "workflow_applied", "workflow_id": wf["id"], "title": title})
        return tool_json(refused=False, content=json.dumps({"workflow_id": wf["id"]}))

    save_flow.tool_info = {
        "name": "save_flow",
        "description": "Save approved flow_json as agent_authored workflow.",
    }
    tools.append(save_flow)

    def run_workflow(_workflow_id: str) -> str:
        return tool_json(
            refused=True,
            error="Workflow execution ships in Phase 7b (LightFlow). Use the Workflows library Run action.",
        )

    run_workflow.tool_info = {
        "name": "run_workflow",
        "description": "Execute saved workflow (Phase 7b — not available in agent authoring).",
    }
    tools.append(run_workflow)

    return tools
