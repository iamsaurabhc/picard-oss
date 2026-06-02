import json
import uuid

import pytest

from app.db.models import Chunk, Document, Entity, EntityMention, TabularReview, Workspace
from app.db.session import utc_now_iso
from app.schemas import TabularColumn
from app.services.tabular_retrieval import gather_cell_chunks
from app.tabular.presets import retrieval_policy_for_column


@pytest.fixture()
def retrieval_fixture(db_session):
    ws_id = str(uuid.uuid4())
    now = utc_now_iso()
    db_session.add(Workspace(id=ws_id, name="Retrieval", matter_ref=None, created_at=now, updated_at=now))
    db_session.flush()
    doc_id = str(uuid.uuid4())
    db_session.add(
        Document(
            id=doc_id,
            workspace_id=ws_id,
            file_name="order.pdf",
            local_path="/tmp/order.pdf",
            parse_status="done",
            created_at=now,
        )
    )
    db_session.flush()

    early_id = str(uuid.uuid4())
    late_id = str(uuid.uuid4())
    db_session.add(
        Chunk(
            id=early_id,
            document_id=doc_id,
            page_number=1,
            chunk_type="paragraph",
            bbox_json="{}",
            text_content="IN THE MATTER OF Google LLC and Informant-1 opposite parties to the proceeding.",
            heading_path=None,
            section_key=None,
            token_count=20,
        )
    )
    db_session.add(
        Chunk(
            id=late_id,
            document_id=doc_id,
            page_number=20,
            chunk_type="paragraph",
            bbox_json="{}",
            text_content="Confidentiality obligations shall survive termination of this investigation for three years.",
            heading_path=None,
            section_key=None,
            token_count=20,
        )
    )
    entity_id = str(uuid.uuid4())
    db_session.add(
        Entity(
            id=entity_id,
            workspace_id=ws_id,
            entity_type="party",
            canonical_value="google llc",
            display_value="Google LLC",
        )
    )
    db_session.add(
        EntityMention(
            id=str(uuid.uuid4()),
            entity_id=entity_id,
            document_id=doc_id,
            chunk_id=early_id,
            page_number=1,
            char_start=None,
            char_end=None,
            surface_text="Google LLC",
            confidence=0.9,
            source="rule",
        )
    )
    db_session.commit()
    return {"ws_id": ws_id, "doc_id": doc_id, "early_id": early_id, "late_id": late_id}


def test_parties_policy_includes_early_and_entity(db_session, retrieval_fixture):
    f = retrieval_fixture
    column = TabularColumn(
        key="parties",
        label="Parties",
        format="bulleted_list",
        prompt="List all parties.",
    )
    policy = retrieval_policy_for_column("parties")
    assert "early_pages" in policy.strategies
    assert "entity_index" in policy.strategies

    hits = gather_cell_chunks(
        db_session,
        document_id=f["doc_id"],
        workspace_id=f["ws_id"],
        column=column,
    )
    chunk_ids = {h.chunk_id for h in hits}
    assert f["early_id"] in chunk_ids


def test_termination_policy_is_fts_only(db_session, retrieval_fixture):
    f = retrieval_fixture
    column = TabularColumn(
        key="termination",
        label="Termination",
        format="text",
        prompt="termination notice cure period",
    )
    policy = retrieval_policy_for_column("termination")
    assert policy.strategies == ("fts",)
