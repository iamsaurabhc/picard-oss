from app.services.citations import build_citation_map, build_system_prompt
from app.schemas import SearchHit
from app.services.listing_map_reduce import build_listing_map_prompt, build_listing_reduce_prompt


def _hit(doc_id: str, text: str, page: int = 1) -> SearchHit:
    return SearchHit(
        chunk_id=f"c-{doc_id}",
        document_id=doc_id,
        page_number=page,
        text_content=text,
        heading_path=None,
        score=1.0,
    )


def test_listing_prompt_has_per_document_structure():
    hits = [
        _hit("d1", "Google LLC is the respondent.", 2),
        _hit("d2", "Informants filed against Google LLC.", 1),
    ]
    cmap = build_citation_map(
        hits,
        doc_names={"d1": "Order-A.pdf", "d2": "Order-B.pdf"},
    )
    prompt = build_system_prompt(
        cmap,
        intent="entity_matter_listing",
        target_entity="google llc",
    )
    assert "entity_matter_listing" not in prompt
    assert "## Summary" in prompt
    assert "Do NOT merge facts from different documents" in prompt
    assert "google llc" in prompt
    assert "Order-A.pdf" in prompt or "document filename" in prompt.casefold()


def test_listing_map_prompt_has_contrastive_and_sources():
    hits = [_hit("d1", "Google LLC is respondent.", 2)]
    cmap = build_citation_map(hits, doc_names={"d1": "Order-A.pdf"})
    prompt = build_listing_map_prompt(
        cmap,
        file_name="Order-A.pdf",
        target_entity="google llc",
    )
    assert "per-document matter brief" in prompt
    assert "Sources:" in prompt
    assert "[1]" in prompt


def test_listing_reduce_prompt_covers_all_briefs():
    prompt = build_listing_reduce_prompt(
        [
            ("Order-A.pdf", "- **Role:** respondent [1]"),
            ("Order-B.pdf", "- **Forum:** CCI [1]"),
        ],
        target_entity="google llc",
        total_discovered=2,
        shown_count=2,
    )
    assert "Discovered: 2 documents" in prompt
    assert "Brief for: Order-A.pdf" in prompt
    assert "Brief for: Order-B.pdf" in prompt
    assert "Include all 2" in prompt
