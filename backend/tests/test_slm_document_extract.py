import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Chunk, Document, Entity, PageEntity, Workspace
from app.db.session import utc_now_iso
from app.services.entity_extraction.slm_document import extract_document_semantics


def _seed_doc(db: Session, text: str) -> str:
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="test", matter_ref=None, created_at=now, updated_at=now)
    db.add(ws)
    doc = Document(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        file_name="google-cci.pdf",
        local_path="google-cci.pdf",
        content_hash="hash",
        parse_status="done",
        page_count=1,
        created_at=now,
    )
    db.add(doc)
    db.add(
        Chunk(
            id=str(uuid.uuid4()),
            document_id=doc.id,
            page_number=1,
            chunk_type="paragraph",
            bbox_json=json.dumps({"x0": 0, "y0": 0, "x1": 1, "y1": 0.4}),
            text_content=text,
            heading_path=None,
            section_key="p1",
            token_count=50,
        )
    )
    db.commit()
    return doc.id


def test_slm_document_extract_writes_google_party(db_session, monkeypatch):
    settings.enable_slm_entity_extract = True
    settings.enable_rule_entity_extract = False
    doc_id = _seed_doc(
        db_session,
        "In the matter of Competition Commission of India vs Google LLC, defendant.",
    )
    payload = {
        "parties": [
            {"display": "Google LLC", "role": "defendant", "pages": [1]},
        ],
        "dates": [],
        "identifiers": [],
        "doc_type": "regulatory",
    }

    def fake_completion(**kwargs):
        return json.dumps(payload)

    monkeypatch.setattr(
        "app.services.entity_extraction.slm_document.completion",
        fake_completion,
    )
    monkeypatch.setattr(
        "app.services.entity_extraction.slm_document.llm_available",
        lambda: True,
    )

    count = extract_document_semantics(db_session, doc_id)
    assert count >= 1

    party = db_session.scalar(
        select(Entity).where(
            Entity.entity_type == "party",
            Entity.canonical_value.like("%google%"),
        )
    )
    assert party is not None
    pe = db_session.get(PageEntity, (doc_id, 1, party.id))
    assert pe is not None
    assert pe.mention_count >= 1
