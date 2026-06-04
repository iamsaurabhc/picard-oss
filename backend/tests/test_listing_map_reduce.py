"""Map-reduce listing: briefs, merge, reduce prompt."""

from __future__ import annotations

from unittest.mock import patch

from app.schemas import SearchHit
from app.services.citations import build_citation_map
from app.services.listing_map_reduce import (
    ListingDocBrief,
    build_listing_reduce_prompt,
    map_document_to_brief,
    merge_listing_briefs,
    should_use_listing_map_reduce,
)


def _hit(doc_id: str, text: str, page: int = 1) -> SearchHit:
    return SearchHit(
        chunk_id=f"c-{doc_id}-{page}",
        document_id=doc_id,
        page_number=page,
        text_content=text,
        heading_path=None,
        score=1.0,
    )


def test_should_use_map_reduce_requires_two_docs():
    assert not should_use_listing_map_reduce(["d1"])
    assert should_use_listing_map_reduce(["d1", "d2"])
    assert not should_use_listing_map_reduce(["d1", "d2"], enabled=False)


def test_merge_listing_briefs_renumbers_citations():
    cmap_a = build_citation_map(
        [_hit("d1", "Google LLC is respondent.")],
        doc_names={"d1": "A.pdf"},
    )
    cmap_b = build_citation_map(
        [_hit("d2", "Google LLC is informant target.")],
        doc_names={"d2": "B.pdf"},
    )
    briefs = [
        ListingDocBrief("d1", "A.pdf", "- **Role:** respondent [1]", cmap_a),
        ListingDocBrief("d2", "B.pdf", "- **Role:** opposite party [1]", cmap_b),
    ]
    sections, merged = merge_listing_briefs(briefs)
    assert len(sections) == 2
    assert len(merged.refs) == 2
    assert "[1]" in sections[0][1]
    assert "[2]" in sections[1][1]


def test_reduce_prompt_includes_total_and_contrastive():
    prompt = build_listing_reduce_prompt(
        [("A.pdf", "- **Role:** respondent [1]")],
        target_entity="google llc",
        total_discovered=7,
        shown_count=2,
    )
    assert "Discovered: 7 documents" in prompt
    assert "top 2" in prompt
    assert "google llc" in prompt.casefold()
    assert "Do NOT merge facts" in prompt
    assert "Brief for: A.pdf" in prompt


@patch("app.services.listing_map_reduce.completion")
@patch("app.services.listing_map_reduce.build_document_context")
@patch("app.services.listing_map_reduce.retrieve_hits_for_listing_document")
def test_map_document_produces_brief(mock_retrieve, mock_doc_ctx, mock_completion):
    from unittest.mock import MagicMock

    from app.services.query_understanding import QueryUnderstanding, TargetEntity

    mock_completion.return_value = "- **Role of party:** respondent [1]"
    mock_retrieve.return_value = [_hit("d1", "Google LLC is the opposite party.")]
    ctx = MagicMock()
    ctx.to_prompt_block.return_value = ""
    mock_doc_ctx.return_value = ctx

    u = QueryUnderstanding(
        intent="entity_matter_listing",
        target_entity=TargetEntity(canonical="google llc", surfaces=[], resolved_canonicals=[]),
    )
    brief = map_document_to_brief(
        None,  # type: ignore[arg-type]
        workspace_id="ws",
        document_id="d1",
        file_name="A.pdf",
        understanding=u,
        query="list cases",
        canonicals=["google llc"],
        doc_names={"d1": "A.pdf"},
    )
    assert brief.file_name == "A.pdf"
    assert "respondent" in brief.brief_markdown
    assert len(brief.citation_map.refs) == 1
