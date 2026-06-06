from app.services.citations import build_citation_map
from app.services.entity_page_chunks import dedupe_hits_by_page, is_substantive_chunk_text
from app.services.entity_page_context import best_representative_chunk, chunk_text_quality_score
from app.services.query_understanding import _overview_sub_questions_from_facets
from app.schemas import SearchHit


def test_chunk_text_quality_prefers_substantive_over_ocr_noise():
    noise = "78FCR456 DEFENDANT, (2003) I W HfGH COURT Ltd, SASR254 protected only by a railing"
    good = (
        "The plaintiff claimed damages in the sum of £1,000. The infant son of the plaintiff "
        "fell into an open drain while passing along the highway."
    )
    assert chunk_text_quality_score(good) > chunk_text_quality_score(noise)


def test_best_representative_chunk_picks_substantive():
    class C:
        def __init__(self, cid: str, text: str):
            self.chunk_id = cid
            self.text_content = text
            self.heading_path = None
            self.section_key = None
            self.bbox_json = "{}"

    chunks = [
        C("noise", "78FCR456 DEFENDANT SASR254 PLAINTIFF railing under w"),
        C(
            "good",
            "The plaintiff claimed damages in the sum of £1,000 for nervous shock and injury.",
        ),
    ]
    best = best_representative_chunk(chunks)
    assert best is not None
    assert best.chunk_id == "good"


def test_is_substantive_chunk_text_rejects_short_noise():
    assert not is_substantive_chunk_text("78FCR456 DEFENDANT SASR254")
    assert is_substantive_chunk_text(
        "The Council of the Municipality of Waverley was engaged in excavation work near the highway."
    )


def test_overview_page_level_excerpt_surfaces_damages_sentence():
    noise_prefix = (
        "W.N. (N.S.W.) 221. COR- The defendant pleaded not guilty, and in a second plea, "
        "1939. after notice, was added during the course of the hearing."
    )
    damages = "The plaintiff claimed damages in the sum of £1,000."
    full = f"{noise_prefix} {damages} The infant son fell into the drain."
    hit = SearchHit(
        chunk_id="page3",
        document_id="doc",
        page_number=3,
        text_content=full,
        heading_path=None,
        score=0.0,
    )
    cmap = build_citation_map(
        [hit],
        page_level=True,
        intent="case_overview",
        prefer_amounts=True,
        question="give case details on Chester v Waverley",
        sub_questions=_overview_sub_questions_from_facets(),
        excerpt_chars=1200,
    )
    preview = cmap.refs[0].preview
    assert "£1,000" in preview or "1,000" in preview
    assert preview.index("1,000") < 200 or preview.index("£1,000") < 200


def test_dedupe_hits_by_page_keeps_richest_text():
    hits = [
        SearchHit(
            chunk_id="a",
            document_id="d1",
            page_number=1,
            text_content="short",
            heading_path=None,
            score=0.0,
        ),
        SearchHit(
            chunk_id="b",
            document_id="d1",
            page_number=1,
            text_content="much longer merged page text for the model",
            heading_path=None,
            score=1.0,
        ),
    ]
    out = dedupe_hits_by_page(hits)
    assert len(out) == 1
    assert out[0].chunk_id == "b"
