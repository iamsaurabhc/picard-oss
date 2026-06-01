import uuid

from app.db.models import Document, Workspace
from app.db.session import utc_now_iso
from app.services.metadata_extractor import extract_metadata_for_document
from app.config import settings


def test_rule_metadata_nda(db_session):
    settings.enable_metadata_llm = False
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="T", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    doc = Document(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        file_name="acme_nda_agreement.pdf",
        local_path="pdfs/x.pdf",
        content_hash="h",
        parse_status="done",
        created_at=now,
    )
    db_session.add(doc)
    db_session.commit()

    extract_metadata_for_document(db_session, doc.id)
    from app.db.models import MetadataTag
    from sqlalchemy import select

    tags = db_session.scalars(select(MetadataTag).where(MetadataTag.document_id == doc.id)).all()
    keys = {t.tag_key: t.tag_value for t in tags}
    assert keys.get("doc_type") == "nda"
