from app.services.citations import build_citation_map, build_system_prompt
from app.schemas import SearchHit


def _hit(text: str, page: int = 1) -> SearchHit:
    return SearchHit(
        chunk_id="c1",
        document_id="d1",
        page_number=page,
        text_content=text,
        heading_path="Intro > Parties",
        score=1.0,
    )


def test_overview_prompt_has_required_sections():
    cmap = build_citation_map([_hit("The plaintiff Janet Chester claimed £1,000.", page=3)], doc_names={"d1": "Chester.pdf"})
    prompt = build_system_prompt(cmap, intent="case_overview")
    for section in ["## Parties", "## Damages / relief sought", "## Nature of claim", "## Outcome / holdings"]:
        assert section in prompt
    assert "CASE OVERVIEW" in prompt
    assert "Excerpt:" in prompt
    assert "central events" in prompt.casefold()
    assert "claimant/plaintiff" in prompt.casefold()
