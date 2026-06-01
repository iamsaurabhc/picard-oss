import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, Workspace
from app.db.session import get_db, utc_now_iso
from app.schemas import DocumentOut, DocumentRetryAllOut
from app.services.ingestion import enqueue_parse_document, retry_parse_document, retry_stuck_documents
from app.services.storage import delete_pdf, resolve_pdf_path, save_pdf

router = APIRouter(tags=["documents"])


@router.get("/workspaces/{workspace_id}/documents", response_model=list[DocumentOut])
def list_documents(workspace_id: str, db: Session = Depends(get_db)):
    if not db.get(Workspace, workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return db.scalars(
        select(Document).where(Document.workspace_id == workspace_id).order_by(Document.created_at.desc())
    ).all()


@router.post("/workspaces/{workspace_id}/documents", response_model=DocumentOut)
async def upload_document(
    workspace_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not db.get(Workspace, workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported in Phase 1")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    content_hash = __import__("hashlib").sha256(data).hexdigest()
    existing = db.scalar(
        select(Document).where(
            Document.workspace_id == workspace_id,
            Document.content_hash == content_hash,
        )
    )
    if existing:
        return existing

    doc_id = str(uuid.uuid4())
    rel_path, _ = save_pdf(workspace_id, doc_id, data)
    now = utc_now_iso()
    doc = Document(
        id=doc_id,
        workspace_id=workspace_id,
        file_name=file.filename,
        local_path=rel_path,
        content_hash=content_hash,
        parse_status="pending",
        created_at=now,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    enqueue_parse_document(doc.id)
    return doc


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/documents/{document_id}/file")
def get_document_file(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    path = resolve_pdf_path(doc.local_path)
    return FileResponse(path, media_type="application/pdf", filename=doc.file_name)


@router.post("/documents/{document_id}/retry")
def retry_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        job_id = retry_parse_document(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"job_id": job_id, "document_id": document_id}


@router.post("/workspaces/{workspace_id}/documents/retry-all", response_model=DocumentRetryAllOut)
def retry_all_documents(workspace_id: str, db: Session = Depends(get_db)):
    if not db.get(Workspace, workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    document_ids = retry_stuck_documents(workspace_id)
    return DocumentRetryAllOut(retried_count=len(document_ids), document_ids=document_ids)


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    delete_pdf(doc.local_path)
    db.delete(doc)
    db.commit()
