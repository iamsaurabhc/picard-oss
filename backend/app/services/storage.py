import hashlib
from pathlib import Path

from fastapi import HTTPException

from app.config import settings


def ensure_data_dirs() -> None:
    settings.picard_data_dir.mkdir(parents=True, exist_ok=True)
    settings.pdfs_dir.mkdir(parents=True, exist_ok=True)
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    if settings.enable_hybrid_search:
        settings.embedding_model_cache_path.mkdir(parents=True, exist_ok=True)


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def workspace_pdf_dir(workspace_id: str) -> Path:
    return settings.pdfs_dir / workspace_id


def save_pdf(workspace_id: str, document_id: str, data: bytes) -> tuple[str, str]:
    dest_dir = workspace_pdf_dir(workspace_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    rel_path = f"pdfs/{workspace_id}/{document_id}.pdf"
    abs_path = settings.picard_data_dir / rel_path
    abs_path.write_bytes(data)
    return rel_path, hash_bytes(data)


def resolve_pdf_path(relative_path: str) -> Path:
    if ".." in relative_path.replace("\\", "/").split("/"):
        raise HTTPException(status_code=400, detail="Invalid path")
    abs_path = (settings.picard_data_dir / relative_path).resolve()
    data_root = settings.picard_data_dir.resolve()
    if not str(abs_path).startswith(str(data_root)):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return abs_path


def delete_pdf(relative_path: str) -> None:
    try:
        path = resolve_pdf_path(relative_path)
        path.unlink(missing_ok=True)
    except HTTPException:
        pass
