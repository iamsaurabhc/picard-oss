import json
import uuid

from app.db.models import Chunk, Document, Entity, EntityMention, PageEntity, Workspace
from app.db.session import utc_now_iso
from app.services.entity_index import extract_entities_for_document, normalize_party
from app.services.entity_listing_retrieval import entity_listing_retrieve
from app.services.query_understanding import TargetEntity, QueryUnderstanding


def _seed_google_doc(db_session, ws_id: str, file_name: str, text: str) -> str:
    now = utc_now_iso()
    doc_id = str(uuid.uuid4())
    doc = Document(
        id=doc_id,
        workspace_id=ws_id,
        file_name=file_name,
        local_path=f"pdfs/{file_name}",
        content_hash=str(uuid.uuid4()),
        parse_status="done",
        page_count=2,
        created_at=now,
    )
    db_session.add(doc)
    chunk = Chunk(
        id=str(uuid.uuid4()),
        document_id=doc_id,
        page_number=1,
        chunk_type="paragraph",
        bbox_json=json.dumps({"x0": 0, "y0": 0, "x1": 1, "y1": 0.5}),
        text_content=text,
        heading_path="Caption",
        section_key="s1",
        token_count=20,
    )
    db_session.add(chunk)
    db_session.commit()
    extract_entities_for_document(db_session, doc_id)
    return doc_id


def test_entity_listing_covers_multiple_documents(db_session):
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="CCI", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    db_session.commit()

    doc_a = _seed_google_doc(
        db_session,
        ws.id,
        "Matrimony-v-Google.pdf",
        "Informants alleged Google LLC contravened Section 4 of the Competition Act.",
    )
    doc_b = _seed_google_doc(
        db_session,
        ws.id,
        "Informants-v-Google.pdf",
        "The Commission issued notice to Google LLC and Google India Private Limited.",
    )
    _seed_google_doc(
        db_session,
        ws.id,
        "Unrelated-Nda.pdf",
        "This agreement between Alpha Ltd and Beta Ltd has no Google party.",
    )

    canonical = normalize_party("Google LLC")
    understanding = QueryUnderstanding(
        intent="entity_matter_listing",
        target_entity=TargetEntity(
            canonical=canonical,
            surfaces=["Google LLC"],
            resolved_canonicals=[canonical],
        ),
    )
    hits, diag = entity_listing_retrieve(
        db_session,
        understanding,
        workspace_id=ws.id,
        query="list all cases against Google LLC",
    )

    doc_ids = {h.document_id for h in hits}
    assert diag["documents_discovered"] >= 2
    assert doc_a in doc_ids
    assert doc_b in doc_ids
    assert len(doc_ids) >= 2
