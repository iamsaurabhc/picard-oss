"""Server-side DOCX mutations via scripts/docx-agent/mutate.mjs (@superdoc-dev/sdk)."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import Document
from app.services.ingestion import enqueue_parse_document
from app.services.storage import hash_bytes, resolve_document_path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
MUTATE_SCRIPT = REPO_ROOT / "scripts" / "docx-agent" / "mutate.mjs"
DEFAULT_TIMEOUT_S = 120


class DocxAgentError(RuntimeError):
    pass


def _node_available() -> bool:
    return shutil.which("node") is not None


def _run_mutate_script(args: list[str], *, timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
    if not _node_available():
        raise DocxAgentError("node is required for SuperDoc SDK mutations")
    if not MUTATE_SCRIPT.is_file():
        raise DocxAgentError(f"Missing sidecar script: {MUTATE_SCRIPT}")
    cmd = ["node", str(MUTATE_SCRIPT), *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            cwd=MUTATE_SCRIPT.parent,
        )
    except subprocess.TimeoutExpired as exc:
        raise DocxAgentError(f"SuperDoc mutation timed out after {timeout_s}s") from exc
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        detail = stderr or stdout or f"exit {proc.returncode}"
        try:
            payload = json.loads(detail)
            if isinstance(payload, dict) and payload.get("error"):
                raise DocxAgentError(str(payload["error"]))
        except json.JSONDecodeError:
            pass
        raise DocxAgentError(detail)
    if not stdout:
        return {}
    try:
        payload = json.loads(stdout)
        return payload if isinstance(payload, dict) else {"result": payload}
    except json.JSONDecodeError:
        return {"raw": stdout}


def _require_docx(doc: Document) -> Path:
    file_type = getattr(doc, "file_type", None) or "pdf"
    if file_type != "docx":
        raise DocxAgentError("Document is not DOCX")
    path = resolve_document_path(doc.local_path)
    if not path.is_file():
        raise DocxAgentError(f"DOCX file not found: {path}")
    return path


def search_docx_text(doc_path: Path, pattern: str) -> list[dict]:
    payload = _run_mutate_script([str(doc_path), "search", pattern])
    matches = payload.get("matches")
    return matches if isinstance(matches, list) else []


def replace_docx_text(
    doc_path: Path,
    *,
    pattern: str,
    replacement: str,
    tracked: bool = True,
) -> bytes:
    args = [str(doc_path), "replace", pattern, replacement]
    if tracked:
        args.append("--tracked")
    _run_mutate_script(args)
    return doc_path.read_bytes()


def apply_docx_mutation(
    db: Session,
    document_id: str,
    *,
    pattern: str,
    replacement: str,
    tracked: bool = True,
    reindex: bool = True,
) -> Document:
    doc = db.get(Document, document_id)
    if not doc:
        raise DocxAgentError("Document not found")
    path = _require_docx(doc)
    updated = replace_docx_text(path, pattern=pattern, replacement=replacement, tracked=tracked)
    path.write_bytes(updated)
    doc.content_hash = hash_bytes(updated)
    doc.parse_status = "pending"
    doc.parse_error = None
    db.commit()
    db.refresh(doc)
    if reindex:
        enqueue_parse_document(doc.id)
    return doc


def build_docx_suggestion(
    *,
    document_id: str,
    find: str,
    replace: str,
    change_mode: str = "tracked",
    rationale: str | None = None,
) -> dict:
    return {
        "document_id": document_id,
        "find": find,
        "replace": replace,
        "change_mode": change_mode,
        "rationale": rationale,
    }
