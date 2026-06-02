import uuid

from app.db.models import Entity, EntityMention, MetadataTag, Chunk, Document, Workspace
from app.db.session import utc_now_iso
from app.services.tabular_grounding import (
    build_tabular_grounding,
    metadata_summary_misses,
    parties_summary_misses_index,
)


def test_parties_summary_misses_index_detects_not_specified():
    assert parties_summary_misses_index("Not specified", ["Google LLC"])


def test_parties_summary_misses_index_accepts_match():
    assert not parties_summary_misses_index(
        "• Google LLC — respondent",
        ["Google LLC", "Informant-1"],
    )


def test_build_tabular_grounding_includes_indexed_parties(db_session):
    ws_id = str(uuid.uuid4())
    now = utc_now_iso()
    db_session.add(Workspace(id=ws_id, name="G", matter_ref=None, created_at=now, updated_at=now))
    db_session.flush()
    doc_id = str(uuid.uuid4())
    db_session.add(
        Document(
            id=doc_id,
            workspace_id=ws_id,
            file_name="f.pdf",
            local_path="/tmp/f.pdf",
            parse_status="done",
            created_at=now,
        )
    )
    db_session.flush()
    chunk_id = str(uuid.uuid4())
    db_session.add(
        Chunk(
            id=chunk_id,
            document_id=doc_id,
            page_number=1,
            chunk_type="paragraph",
            bbox_json="{}",
            text_content="Caption text with Google LLC as respondent in this matter before the commission.",
            heading_path=None,
            section_key=None,
            token_count=12,
        )
    )
    eid = str(uuid.uuid4())
    db_session.add(
        Entity(
            id=eid,
            workspace_id=ws_id,
            entity_type="party",
            canonical_value="google",
            display_value="Google LLC",
        )
    )
    db_session.add(
        EntityMention(
            id=str(uuid.uuid4()),
            entity_id=eid,
            document_id=doc_id,
            chunk_id=chunk_id,
            page_number=1,
            char_start=None,
            char_end=None,
            surface_text="Google LLC",
            confidence=1.0,
            source="rule",
        )
    )
    db_session.add(
        MetadataTag(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            tag_key="party_1",
            tag_value="Google LLC",
            source_chunk_id=chunk_id,
        )
    )
    db_session.commit()

    text = build_tabular_grounding(
        db_session,
        document_id=doc_id,
        workspace_id=ws_id,
        column_key="parties",
    )
    assert "Google LLC" in text
    assert "Indexed evidence" in text


def test_build_tabular_grounding_includes_governing_law_and_doc_type(db_session):
    ws_id = str(uuid.uuid4())
    now = utc_now_iso()
    db_session.add(Workspace(id=ws_id, name="G", matter_ref=None, created_at=now, updated_at=now))
    db_session.flush()
    doc_id = str(uuid.uuid4())
    db_session.add(
        Document(
            id=doc_id,
            workspace_id=ws_id,
            file_name="cci_order.pdf",
            local_path="/tmp/cci.pdf",
            parse_status="done",
            created_at=now,
        )
    )
    db_session.flush()
    db_session.add(
        MetadataTag(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            tag_key="doc_type",
            tag_value="regulatory",
            source_chunk_id=None,
        )
    )
    db_session.add(
        MetadataTag(
            id=str(uuid.uuid4()),
            document_id=doc_id,
            tag_key="governing_law",
            tag_value="Competition Act 2002, India",
            source_chunk_id=None,
        )
    )
    db_session.commit()

    text = build_tabular_grounding(
        db_session,
        document_id=doc_id,
        workspace_id=ws_id,
        column_key="governing_law",
        file_name="cci_order.pdf",
    )
    assert "regulatory" in text
    assert "Competition Act" in text


def test_metadata_summary_misses():
    assert metadata_summary_misses(
        "Not specified",
        {"governing_law": "Competition Act 2002, India"},
    )
    assert not metadata_summary_misses(
        "Competition Act 2002, India",
        {"governing_law": "Competition Act 2002, India"},
    )
