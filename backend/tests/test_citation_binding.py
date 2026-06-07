from app.services.citation_binding import (
    ChunkCandidate,
    best_chunk_for_claim,
    best_ref_index_for_claim,
    ref_binding_surfaces,
)
from app.services.citations import CitationRef, CitationMap, references_for_api


def test_score_claim_to_chunk_substring_match():
    chunk = "Case No. 39 of 2018 Competition Commission of India"
    claim = chunk + " — matter under consideration"
    from app.services.citation_binding import score_claim_to_chunk

    assert score_claim_to_chunk(claim, chunk) == 1.0


def test_best_ref_index_for_claim_picks_court_chunk():
    refs = [
        CitationRef(
            index=1,
            chunk_id="party",
            document_id="d1",
            page=2,
            bbox=None,
            preview="The present Information has been filed by Mr. Umar Javeed under Section 19",
            page_chunks=[
                {"chunk_id": "party", "text": "filed by informants under Section 19", "page": 2},
            ],
        ),
        CitationRef(
            index=2,
            chunk_id="court",
            document_id="d1",
            page=1,
            bbox={"x0": 0.1, "y0": 0.05, "x1": 0.9, "y1": 0.12},
            preview="Competition Commission of India Case No. 39 of 2018",
            page_chunks=[
                {
                    "chunk_id": "court",
                    "text": "Competition Commission of India Case No. 39 of 2018",
                    "page": 1,
                    "bbox": {"x0": 0.1, "y0": 0.05, "x1": 0.9, "y1": 0.12},
                },
            ],
        ),
    ]
    claim = "The case is before the Competition Commission of India, Case No. 39 of 2018"
    idx, score = best_ref_index_for_claim(claim, refs)
    assert idx == 2
    assert score >= 0.25


def test_best_chunk_for_claim_token_overlap():
    candidates = [
        ChunkCandidate(chunk_id="a", text="plaintiff claimed damages sum"),
        ChunkCandidate(chunk_id="b", text="court discussed remote damage doctrine"),
    ]
    best, score = best_chunk_for_claim("damages sum claimed by plaintiff", candidates)
    assert best is not None
    assert best.chunk_id == "a"
    assert score > 0.25


def test_ref_binding_surfaces_includes_page_chunks():
    ref = CitationRef(
        index=3,
        chunk_id="a",
        document_id="d1",
        page=2,
        bbox=None,
        preview="informants filed",
        page_chunks=[{"chunk_id": "b", "text": "Case No. 39 of 2018", "page": 1}],
    )
    texts = [s.text for s in ref_binding_surfaces(ref)]
    assert any("Case No. 39" in t for t in texts)


def test_court_claim_rejects_scattered_digits_without_number_phrase():
    from app.services.citation_binding import score_claim_to_chunk

    prima_facie = (
        "In the aforesaid backdrop, the Commission is of the prima facie opinion "
        "that by making pre-installation of Google's proprietary apps mandatory "
        "Google has violated Section 4 in proceedings from 2018 concerning matter 39"
    )
    caption = "Case No. 39 of 2018 Competition Commission of India"
    claim = (
        "The case is before the Competition Commission of India, "
        "Case No. 39 of 2018"
    )
    assert score_claim_to_chunk(claim, caption) > score_claim_to_chunk(
        claim, prima_facie
    )


def test_court_claim_prefers_case_number_chunk_over_commission_prose():
    from app.services.citation_binding import score_claim_to_chunk

    informants = (
        "The present Information has been filed under Section 19(1)(a) of the "
        "Competition Act, 2002 before the Competition Commission of India alleging abuse"
    )
    court = "Case No. 39 of 2018 Competition Commission of India"
    claim = (
        "The case is before the Competition Commission of India, "
        "under case number 39 of 2018"
    )
    assert score_claim_to_chunk(claim, court) > score_claim_to_chunk(claim, informants)


def test_references_for_api_includes_document_binding_chunks():
    cmap = CitationMap(
        refs=[
            CitationRef(
                index=1,
                chunk_id="court",
                document_id="d1",
                page=1,
                bbox=None,
                preview="Case No. 39 of 2018",
                page_chunks=[{"chunk_id": "court", "text": "Case No. 39 of 2018", "page": 1}],
            ),
            CitationRef(
                index=3,
                chunk_id="body",
                document_id="d1",
                page=2,
                bbox=None,
                preview="Section 19 filing",
            ),
        ],
        chunk_id_to_index={"court": 1, "body": 3},
        bundle_chunk_ids={},
    )
    api = references_for_api(cmap, answer="Court [1] and filing [3]", cited_only=True)
    assert len(api) == 2
    court_binding = api[0].get("document_binding_chunks") or []
    assert any("Case No. 39" in (c.get("text") or "") for c in court_binding)
    filing_binding = api[1].get("document_binding_chunks") or []
    assert all(c.get("page") == 2 for c in filing_binding)
