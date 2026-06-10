import json
import uuid

from app.db.models import Chunk, Document, MetadataTag, Workspace
from app.db.session import utc_now_iso
from app.services.document_profile import (
    PROFILE_TAG_KEY,
    build_profile_v0_from_chunks,
    load_profile,
    save_profile_v0,
)
from app.services.query_understanding import (
    QueryUnderstanding,
    _apply_profile_structural_guard,
    _merge_profile_into_understanding,
)
from app.services.document_context import DocumentContext


def _chunk(**kwargs) -> Chunk:
    defaults = {
        "document_id": "doc1",
        "page_number": 1,
        "bbox_json": "{}",
        "heading_path": "Playbook",
        "section_key": "abc",
        "token_count": 10,
    }
    defaults.update(kwargs)
    return Chunk(id=str(uuid.uuid4()), **defaults)


def test_build_profile_v0_table_row_primary_unit():
    chunks = [
        _chunk(chunk_type="table_header", text_content="Table columns: Clause | Preferred"),
        _chunk(chunk_type="table_row", text_content="Clause: Standstill\nPreferred: 6 months"),
        _chunk(chunk_type="table_row", text_content="Clause: Representatives\nPreferred: include affiliates"),
    ]
    profile = build_profile_v0_from_chunks(chunks)
    assert profile.structure["primary_unit"] == "table_row"
    assert profile.structure["table_row_count"] == 2


def test_save_and_load_profile(db_session):
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="T", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    doc_id = str(uuid.uuid4())
    db_session.add(
        Document(
            id=doc_id,
            workspace_id=ws.id,
            file_name="playbook.docx",
            local_path="x/y.docx",
            parse_status="done",
            created_at=now,
        )
    )
    chunk = _chunk(document_id=doc_id, chunk_type="table_row", text_content="Clause: A")
    db_session.add(chunk)
    db_session.flush()
    save_profile_v0(db_session, doc_id, [chunk])
    db_session.commit()
    loaded = load_profile(db_session, doc_id, use_cache=False)
    assert loaded.structure["primary_unit"] == "table_row"


def test_profile_guard_downgrades_case_overview_for_table_row():
    ctx = DocumentContext(
        document_profiles={
            "doc1": {
                "canonical_kind": "nda playbook",
                "synthesis_outline": ["Purpose", "Clauses"],
                "structure": {"primary_unit": "table_row"},
                "anti_patterns": ["Do not use litigation skeleton"],
            }
        }
    )
    u = QueryUnderstanding(intent="case_overview", used_llm=True)
    guarded = _apply_profile_structural_guard(u, ctx)
    assert guarded.intent == "general"
    assert guarded.synthesis_outline == ["Purpose", "Clauses"]
    assert guarded.retrieval_unit == "table_row"


def test_merge_profile_into_understanding():
    ctx = DocumentContext(
        document_profiles={
            "doc1": {
                "canonical_kind": "negotiation playbook",
                "synthesis_outline": ["Signatories", "Clauses"],
                "structure": {
                    "primary_unit": "table_row",
                    "overview_facets": [
                        {"label": "standstill", "question": "Standstill?", "fts_terms": ["standstill"]},
                    ],
                },
            }
        }
    )
    u = QueryUnderstanding(intent="general")
    merged = _merge_profile_into_understanding(u, ctx)
    assert merged.synthesis_outline == ["Signatories", "Clauses"]
    assert merged.profile_canonical_kind == "negotiation playbook"
    assert merged.retrieval_unit == "table_row"
    assert len(merged.sub_questions) == 1
