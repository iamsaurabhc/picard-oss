from __future__ import annotations

import json
import time

from sqlalchemy import select

from app.db.models import Document, Job
from app.services.agent_hitl import consume_approval, create_approval, scope_hitl_required
from app.services.chat import update_session
from app.schemas import ChatSessionUpdate
from app.services.docx_agent import build_docx_suggestion
from app.tools.context import ToolContext
from app.tools.response import tool_json


def bind_vault_tools(ctx: ToolContext) -> list:
    tools = []

    def list_documents() -> str:
        q = select(Document).where(Document.workspace_id == ctx.workspace_id)
        rows = ctx.db.scalars(q).all()
        docs = [
            {
                "id": d.id,
                "file_name": d.file_name,
                "parse_status": d.parse_status,
                "page_count": d.page_count,
            }
            for d in rows
        ]
        return tool_json(refused=False, content=json.dumps(docs))

    list_documents.tool_info = {
        "name": "list_documents",
        "description": "List documents in the workspace vault.",
    }
    tools.append(list_documents)

    def set_session_scope(document_ids_json: str) -> str:
        try:
            doc_ids = json.loads(document_ids_json)
        except json.JSONDecodeError:
            return tool_json(refused=True, error="document_ids_json must be a JSON array")
        if not isinstance(doc_ids, list):
            return tool_json(refused=True, error="document_ids must be an array")

        if scope_hitl_required(len(doc_ids), ctx.profile) and not ctx.scope_approved:
            token = create_approval(
                session_id=ctx.session_id,
                kind="scope",
                payload={"document_ids": doc_ids},
            )
            ctx.emit(
                {
                    "event": "approval_required",
                    "kind": "scope",
                    "token": token,
                    "document_count": len(doc_ids),
                    "document_ids": doc_ids,
                }
            )
            return tool_json(
                refused=True,
                error="Scope confirmation required. User must approve via UI.",
                approval_token=token,
            )

        update_session(
            ctx.db,
            ctx.session_id,
            ChatSessionUpdate(document_ids=doc_ids),
        )
        ctx.document_ids = doc_ids
        return tool_json(refused=False, content=f"Scope set to {len(doc_ids)} documents.")

    set_session_scope.tool_info = {
        "name": "set_session_scope",
        "description": "Bind document_ids JSON array for corpus tools in this session.",
    }
    tools.append(set_session_scope)

    def wait_parse_job(job_id: str, timeout_seconds: str = "120") -> str:
        deadline = time.time() + float(timeout_seconds)
        while time.time() < deadline:
            job = ctx.db.get(Job, job_id)
            if not job:
                return tool_json(refused=True, error=f"Job {job_id} not found")
            if job.status == "done":
                return tool_json(refused=False, content=json.dumps({"status": "done", "result": job.result_json}))
            if job.status == "error":
                return tool_json(refused=True, error=job.error or "parse failed")
            time.sleep(1.0)
        return tool_json(refused=True, error="timeout waiting for parse job")

    wait_parse_job.tool_info = {
        "name": "wait_parse_job",
        "description": "Poll parse job until done or timeout.",
    }
    tools.append(wait_parse_job)

    def upload_documents(_paths_hint: str = "") -> str:
        return tool_json(
            refused=True,
            error="Use the Picard UI to upload PDFs; then call wait_parse_job on the returned job id.",
        )

    upload_documents.tool_info = {
        "name": "upload_documents",
        "description": "Hint: upload via UI; returns job id for wait_parse_job.",
    }
    tools.append(upload_documents)

    def propose_docx_edit(document_id: str, find: str, replace: str, rationale: str = "") -> str:
        doc = ctx.db.get(Document, document_id)
        if not doc or doc.workspace_id != ctx.workspace_id:
            return tool_json(refused=True, error="Document not found in workspace")
        if (getattr(doc, "file_type", None) or "pdf") != "docx":
            return tool_json(refused=True, error="propose_docx_edit only applies to DOCX files")
        suggestion = build_docx_suggestion(
            document_id=document_id,
            find=find,
            replace=replace,
            change_mode="tracked",
            rationale=rationale or None,
        )
        ctx.emit({"event": "docx_suggestion", **suggestion})
        return tool_json(refused=False, content=json.dumps(suggestion))

    propose_docx_edit.tool_info = {
        "name": "propose_docx_edit",
        "description": (
            "Propose a tracked DOCX find/replace for the user to apply in the vault editor. "
            "Emits docx_suggestion SSE for in-browser review."
        ),
    }
    tools.append(propose_docx_edit)

    return tools
