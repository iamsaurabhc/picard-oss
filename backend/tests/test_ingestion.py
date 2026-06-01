import uuid
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from app.db.models import Chunk, Document, Job
from app.services.entity_index import extract_entities_for_document
from app.services.ingestion import _parse_document_sync


def _make_pdf(path: Path, pages: int = 2) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    for i in range(pages):
        c.drawString(72, 720, f"Confidentiality Agreement Page {i + 1}")
        c.drawString(72, 700, "Party ABC obligations under Condition C.")
        c.drawString(72, 680, "Effective date 18/05/2019.")
        c.showPage()
    c.save()


def test_end_to_end_parse(db_session, tmp_path, monkeypatch, test_sessionmaker):
    from app.config import settings
    from app.db.models import Workspace
    from app.db.session import utc_now_iso
    from app.services import ingestion
    from app.services.storage import save_pdf

    monkeypatch.setattr(settings, "picard_data_dir", tmp_path / "data")
    monkeypatch.setattr(ingestion, "SessionLocal", test_sessionmaker)
    data_dir = settings.picard_data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="Ingest", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    doc_id = str(uuid.uuid4())
    pdf_path = data_dir / "pdfs" / ws.id / f"{doc_id}.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    _make_pdf(pdf_path, pages=2)
    rel_path, content_hash = save_pdf(ws.id, doc_id, pdf_path.read_bytes())

    doc = Document(
        id=doc_id,
        workspace_id=ws.id,
        file_name="sample.pdf",
        local_path=rel_path,
        content_hash=content_hash,
        parse_status="pending",
        created_at=now,
    )
    db_session.add(doc)
    job = Job(
        id=str(uuid.uuid4()),
        job_type="parse",
        payload_json="{}",
        status="pending",
        progress=0,
        created_at=now,
        updated_at=now,
    )
    db_session.add(job)
    db_session.commit()

    _parse_document_sync(doc_id, job.id)

    db_session.refresh(doc)
    assert doc.parse_status == "done"
    assert doc.page_count == 2
    assert doc.text_source == "digital"
    assert doc.ocr_engine == "none"
    chunks = db_session.query(Chunk).filter(Chunk.document_id == doc_id).all()
    assert len(chunks) > 0
    assert all(c.bbox_json for c in chunks)


def test_upload_dedup(client, monkeypatch):
    monkeypatch.setattr("app.services.ingestion._executor.submit", lambda *args, **kwargs: None)
    ws = client.post("/workspaces", json={"name": "Dedup"}).json()
    pdf_bytes = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
    files = {"file": ("same.pdf", pdf_bytes, "application/pdf")}
    r1 = client.post(f"/workspaces/{ws['id']}/documents", files=files)
    assert r1.status_code == 200
    id1 = r1.json()["id"]
    r2 = client.post(f"/workspaces/{ws['id']}/documents", files=files)
    assert r2.status_code == 200
    assert r2.json()["id"] == id1


def test_retry_document(client, monkeypatch):
    submitted: list[str] = []

    def fake_submit(fn, document_id, job_id):
        submitted.append(document_id)

    monkeypatch.setattr("app.services.ingestion._executor.submit", fake_submit)
    ws = client.post("/workspaces", json={"name": "Retry"}).json()
    pdf_bytes = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
    files = {"file": ("doc.pdf", pdf_bytes, "application/pdf")}
    doc = client.post(f"/workspaces/{ws['id']}/documents", files=files).json()
    before = len(submitted)

    r = client.post(f"/documents/{doc['id']}/retry")
    assert r.status_code == 200
    assert r.json()["document_id"] == doc["id"]
    assert len(submitted) == before + 1
    assert submitted[-1] == doc["id"]


def test_retry_all_stuck(client, monkeypatch):
    submitted: list[str] = []

    def fake_submit(fn, document_id, job_id):
        submitted.append(document_id)

    monkeypatch.setattr("app.services.ingestion._executor.submit", fake_submit)
    ws = client.post("/workspaces", json={"name": "RetryAll"}).json()
    pdf_bytes = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
    files = {"file": ("a.pdf", pdf_bytes, "application/pdf")}
    doc = client.post(f"/workspaces/{ws['id']}/documents", files=files).json()
    before = len(submitted)

    r = client.post(f"/workspaces/{ws['id']}/documents/retry-all")
    assert r.status_code == 200
    body = r.json()
    assert body["retried_count"] == 1
    assert body["document_ids"] == [doc["id"]]
    assert len(submitted) == before + 1
    assert submitted[-1] == doc["id"]
