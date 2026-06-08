import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document, Workspace
from app.db.session import get_db, utc_now_iso
from app.schemas import (
    ChunkOut,
    DocxMutateRequest,
    DocxSearchRequest,
    DocxSuggestionOut,
    DocumentConvertToDocxOut,
    DocumentOut,
    DocumentRetryAllOut,
)
from app.services.docx_agent import (
    DocxAgentError,
    apply_docx_mutation,
    build_docx_suggestion,
    search_docx_text,
)
from app.services.ingestion import enqueue_parse_document, retry_parse_document, retry_stuck_documents
from app.services.pdf_to_docx import chunks_to_docx_bytes, chunks_to_docx_for_document
from app.services.storage import (
    delete_document,
    hash_bytes,
    infer_file_type,
    mime_type_for_file_type,
    resolve_document_path,
    save_document,
)

router = APIRouter(tags=["documents"])

ALLOWED_EXTENSIONS = {".pdf", ".docx"}


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
    source_document_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if not db.get(Workspace, workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    file_type = infer_file_type(file.filename)
    if not file_type:
        raise HTTPException(
            status_code=400,
            detail="Only PDF and DOCX uploads are supported",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    content_hash = hash_bytes(data)
    existing = db.scalar(
        select(Document).where(
            Document.workspace_id == workspace_id,
            Document.content_hash == content_hash,
        )
    )
    if existing:
        return existing

    if source_document_id:
        source = db.get(Document, source_document_id)
        if not source or source.workspace_id != workspace_id:
            raise HTTPException(status_code=400, detail="Invalid source_document_id")

    doc_id = str(uuid.uuid4())
    rel_path, _ = save_document(workspace_id, doc_id, data, file_type)
    now = utc_now_iso()
    doc = Document(
        id=doc_id,
        workspace_id=workspace_id,
        file_name=file.filename,
        local_path=rel_path,
        content_hash=content_hash,
        file_type=file_type,
        source_document_id=source_document_id,
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


def _chunk_to_out(chunk: Chunk) -> ChunkOut:
    try:
        bbox = json.loads(chunk.bbox_json)
    except (json.JSONDecodeError, TypeError):
        bbox = {}
    anchor = None
    if chunk.anchor_json:
        try:
            anchor = json.loads(chunk.anchor_json)
        except (json.JSONDecodeError, TypeError):
            anchor = None
    return ChunkOut(
        id=chunk.id,
        document_id=chunk.document_id,
        page_number=chunk.page_number,
        chunk_type=chunk.chunk_type,  # type: ignore[arg-type]
        bbox=bbox,
        text_content=chunk.text_content,
        heading_path=chunk.heading_path,
        section_key=chunk.section_key,
        token_count=chunk.token_count,
        anchor=anchor,
    )


def _sort_chunks(chunks: list[Chunk]) -> list[Chunk]:
    def sort_key(c: Chunk) -> tuple[int, float, float]:
        try:
            bbox = json.loads(c.bbox_json)
            y0 = float(bbox.get("y0", 0))
            x0 = float(bbox.get("x0", 0))
        except (json.JSONDecodeError, TypeError, ValueError):
            y0, x0 = 0.0, 0.0
        return (c.page_number, y0, x0)

    return sorted(chunks, key=sort_key)


@router.get("/documents/{document_id}/chunks", response_model=list[ChunkOut])
def list_document_chunks(
    document_id: str,
    page: int | None = Query(default=None, ge=1),
    limit: int | None = Query(default=None, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    stmt = select(Chunk).where(Chunk.document_id == document_id)
    if page is not None:
        stmt = stmt.where(Chunk.page_number == page)
    chunks = list(db.scalars(stmt).all())
    chunks = _sort_chunks(chunks)

    if offset:
        chunks = chunks[offset:]
    if limit is not None:
        chunks = chunks[:limit]

    return [_chunk_to_out(c) for c in chunks]


@router.get("/documents/{document_id}/file")
def get_document_file(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    path = resolve_document_path(doc.local_path)
    file_type = getattr(doc, "file_type", None) or "pdf"
    return FileResponse(
        path,
        media_type=mime_type_for_file_type(file_type),
        filename=doc.file_name,
    )


@router.post("/documents/{document_id}/docx/search")
def docx_search(document_id: str, body: DocxSearchRequest, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if (getattr(doc, "file_type", None) or "pdf") != "docx":
        raise HTTPException(status_code=400, detail="Only DOCX documents support search")
    try:
        matches = search_docx_text(resolve_document_path(doc.local_path), body.pattern)
    except DocxAgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"document_id": document_id, "pattern": body.pattern, "matches": matches}


@router.post("/documents/{document_id}/docx/mutate", response_model=DocumentOut)
def docx_mutate(document_id: str, body: DocxMutateRequest, db: Session = Depends(get_db)):
    try:
        return apply_docx_mutation(
            db,
            document_id,
            pattern=body.pattern,
            replacement=body.replacement,
            tracked=body.tracked,
            reindex=body.reindex,
        )
    except DocxAgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/documents/{document_id}/docx/suggest", response_model=DocxSuggestionOut)
def docx_suggest(document_id: str, body: DocxMutateRequest, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if (getattr(doc, "file_type", None) or "pdf") != "docx":
        raise HTTPException(status_code=400, detail="Only DOCX documents support suggestions")
    return DocxSuggestionOut(
        **build_docx_suggestion(
            document_id=document_id,
            find=body.pattern,
            replace=body.replacement,
            change_mode="tracked" if body.tracked else "direct",
        )
    )


@router.put("/documents/{document_id}/file", response_model=DocumentOut)
async def update_document_file(
    document_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    file_type = getattr(doc, "file_type", None) or infer_file_type(doc.file_name) or "pdf"
    if file_type != "docx":
        raise HTTPException(status_code=400, detail="Only DOCX documents can be updated in place")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    new_hash = hash_bytes(data)
    if new_hash == doc.content_hash:
        return doc

    path = resolve_document_path(doc.local_path)
    path.write_bytes(data)
    doc.content_hash = new_hash
    doc.parse_status = "pending"
    doc.parse_error = None
    db.commit()
    db.refresh(doc)
    enqueue_parse_document(doc.id)
    return doc


@router.post("/documents/{document_id}/convert-to-docx")
def convert_pdf_to_docx(
    document_id: str,
    method: str = Query(default="chunks", pattern="^(chunks|wasm)$"),
    save: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    file_type = getattr(doc, "file_type", None) or "pdf"
    if file_type != "pdf":
        raise HTTPException(status_code=400, detail="Only PDF documents can be converted to DOCX")

    if method == "wasm":
        raise HTTPException(
            status_code=400,
            detail="WASM conversion runs in the browser — use the vault UI Convert to Word action",
        )

    if doc.parse_status != "done":
        raise HTTPException(status_code=400, detail="PDF must be parsed before chunk-based conversion")

    try:
        docx_bytes = chunks_to_docx_for_document(db, document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not save:
        stem = Path(doc.file_name).stem
        return Response(
            content=docx_bytes,
            media_type=mime_type_for_file_type("docx"),
            headers={"Content-Disposition": f'attachment; filename="{stem}.docx"'},
        )

    new_name = f"{Path(doc.file_name).stem}.docx"
    new_id = str(uuid.uuid4())
    rel_path, content_hash = save_document(doc.workspace_id, new_id, docx_bytes, "docx")
    now = utc_now_iso()
    new_doc = Document(
        id=new_id,
        workspace_id=doc.workspace_id,
        file_name=new_name,
        local_path=rel_path,
        content_hash=content_hash,
        file_type="docx",
        source_document_id=document_id,
        parse_status="pending",
        created_at=now,
    )
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)
    enqueue_parse_document(new_doc.id)
    return DocumentConvertToDocxOut(document_id=new_doc.id, file_name=new_name, method="chunks")


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
def delete_document_route(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    delete_document(doc.local_path)
    db.delete(doc)
    db.commit()
