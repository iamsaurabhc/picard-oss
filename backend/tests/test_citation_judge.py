import json
from unittest.mock import patch

from app.config import settings
from app.services.citations import build_citation_map, build_system_prompt
from app.schemas import SearchHit


def test_build_system_prompt_includes_pinpoint():
    hits = [
        SearchHit(
            chunk_id="c1",
            document_id="d1",
            page_number=3,
            text_content="The plaintiff claimed damages in the sum of £1,000.",
            heading_path="Damages",
            score=1.0,
        )
    ]
    cmap = build_citation_map(hits, doc_names={"d1": "Chester v Waverley.pdf"})
    prompt = build_system_prompt(cmap)
    assert "Chester v Waverley.pdf" in prompt
    assert "Pinpoint:" in prompt
    assert "£1,000" in prompt


def test_citation_judge_disabled():
    from app.services.citation_judge import judge_citations

    settings.enable_citation_judge = False
    hits = [
        SearchHit(
            chunk_id="c1",
            document_id="d1",
            page_number=1,
            text_content="fact",
            heading_path=None,
            score=1.0,
        )
    ]
    cmap = build_citation_map(hits)
    result = judge_citations("Claim [1].", cmap)
    assert result["enabled"] is False
