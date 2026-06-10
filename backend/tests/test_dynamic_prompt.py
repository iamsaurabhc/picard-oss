from app.services.citations import build_citation_map, build_system_prompt
from app.schemas import SearchHit


def _hit(text: str, chunk_type: str = "table_row") -> SearchHit:
    return SearchHit(
        chunk_id="c1",
        document_id="d1",
        page_number=1,
        text_content=text,
        heading_path="Playbook",
        score=1.0,
        chunk_type=chunk_type,
    )


def test_build_system_prompt_uses_synthesis_outline():
    cmap = build_citation_map(
        [_hit("Clause: Standstill\nPreferred: 6 months")],
        excerpt_chars=600,
        retrieval_unit="table_row",
    )
    prompt = build_system_prompt(
        cmap,
        intent="general",
        synthesis_outline=["Purpose", "Signatories", "Clauses"],
        profile_canonical_kind="nda negotiation playbook",
        profile_anti_patterns=["Do not use litigation case skeleton sections"],
    )
    assert "## Purpose" in prompt
    assert "## Signatories" in prompt
    assert "## Clauses" in prompt
    assert "nda negotiation playbook" in prompt
    assert "## Court & citation" not in prompt


def test_table_row_excerpt_in_citation_map():
    cmap = build_citation_map(
        [_hit("Clause: Ownership\nPreferred: Delete representation")],
        excerpt_chars=800,
        retrieval_unit="table_row",
    )
    assert "Ownership" in (cmap.refs[0].preview or "")
