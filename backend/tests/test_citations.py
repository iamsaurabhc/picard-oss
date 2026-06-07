from app.schemas import ContextBundleOut, SearchHit
from app.services.citations import (
    CitationMap,
    CitationRef,
    build_citation_map,
    build_system_prompt,
    references_for_api,
    refuse_gate,
    validate_response,
)
from app.services.excerpt_selector import _best_excerpt, _fallback_excerpt
from app.services.query_understanding import SubQuestion


def _hit(chunk_id: str, doc_id: str = "d1", page: int = 1) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        document_id=doc_id,
        page_number=page,
        text_content=f"text {chunk_id}",
        heading_path=None,
        bbox={"x0": 0.1, "y0": 0.2, "x1": 0.9, "y1": 0.3},
        score=1.0,
    )


def test_build_citation_map_dedupes_chunks():
    hits = [_hit("c1"), _hit("c1"), _hit("c2")]
    cmap = build_citation_map(hits)
    assert len(cmap.refs) == 2
    assert cmap.refs[0].index == 1
    assert cmap.refs[1].index == 2


def test_ct01_all_markers_resolve():
    hits = [_hit("c1"), _hit("c2")]
    cmap = build_citation_map(hits)
    answer = "Claim one [1] and two [2]."
    cleaned, validation = validate_response(answer, cmap)
    assert validation.markers_valid
    assert "[1]" in cleaned and "[2]" in cleaned


def test_invalid_marker_stripped():
    hits = [_hit("c1")]
    cmap = build_citation_map(hits)
    cleaned, validation = validate_response("Bad cite [9]", cmap)
    assert validation.facts_stripped == 1
    assert "[9]" not in cleaned


def test_fg02_cross_bundle_flag():
    hits = [_hit("c1"), _hit("c2")]
    bundles = [
        ContextBundleOut(
            bundle_id="b1",
            document_id="d1",
            page_start=1,
            page_end=1,
            section_key=None,
            heading_path=None,
            chunk_ids=["c1"],
            constraints_matched=[],
            constraints_missing=[],
            proximity_tier="SAME_PAGE",
            bm25_score=0.0,
            coherence_score=0.0,
            score=1.0,
        ),
        ContextBundleOut(
            bundle_id="b2",
            document_id="d1",
            page_start=2,
            page_end=2,
            section_key=None,
            heading_path=None,
            chunk_ids=["c2"],
            constraints_matched=[],
            constraints_missing=[],
            proximity_tier="SAME_PAGE",
            bm25_score=0.0,
            coherence_score=0.0,
            score=1.0,
        ),
    ]
    cmap = build_citation_map(hits, bundles)
    _, validation = validate_response("A [1] and B [2]", cmap, mode="MULTI_CONSTRAINT")
    assert validation.cross_bundle_violation


def test_refuse_gate_empty_hits():
    assert refuse_gate([])
    assert refuse_gate([_hit("c1")]) is False


def test_fallback_excerpt_truncates_long_text():
    text = "a" * 1000
    excerpt = _fallback_excerpt(text, 120)
    assert len(excerpt) <= 121
    assert excerpt.endswith("…")


def test_citation_map_surfaces_name_from_declaration_chunk():
    text = (
        "v. Council of the Municipality of Waverley, (1938) 38 S.R. affirmed. "
        "The plaintiff, Janet Chester, alleged negligence. "
        "Ma x Chester, the infant son of the plaintiff, fell into the drain."
    )
    hit = SearchHit(
        chunk_id="c-decl",
        document_id="d1",
        page_number=2,
        text_content=text,
        heading_path=None,
        bbox=None,
        score=1.0,
    )
    cmap = build_citation_map(
        [hit],
        excerpt_chars=200,
        question="son's name?",
        sub_questions=[SubQuestion(label="son_name", question="Name?", fts_terms=["infant", "son"])],
    )
    preview = cmap.refs[0].preview.casefold()
    assert "infant son" in preview
    assert "ma x" in preview or "chester" in preview


def test_validate_response_splits_reused_markers_by_claim():
    refs = [
        CitationRef(
            index=5,
            chunk_id="filing",
            document_id="d1",
            page=2,
            bbox={"x0": 0.1, "y0": 0.8, "x1": 0.9, "y1": 0.85},
            preview=(
                "The present Information has been filed by Mr. Umar Javeed, "
                "Ms. Sukarma Thapar and Mr. Aaqib Javeed"
            ),
        ),
        CitationRef(
            index=6,
            chunk_id="abuse",
            document_id="d1",
            page=3,
            bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2},
            preview=(
                "abuse of dominant position by Google in the mobile operating "
                "system related markets in contravention of Section 4"
            ),
        ),
    ]
    cmap = CitationMap(
        refs=refs,
        chunk_id_to_index={"filing": 5, "abuse": 6},
        bundle_chunk_ids={},
    )
    answer = (
        "## Parties\n"
        "The informants are Mr. Umar Javeed, Ms. Sukarma Thapar, and Mr. Aaqib Javeed [5].\n\n"
        "## Nature of claim\n"
        "The informants allege abuse of dominant position by Google [5]."
    )
    cleaned, validation = validate_response(answer, cmap, intent="case_overview")
    assert "[5]" in cleaned
    assert "[6]" in cleaned
    assert validation.markers_reassigned >= 1


def test_validate_response_consolidates_duplicate_markers_in_sentence():
    refs = [
        CitationRef(
            index=6,
            chunk_id="c6",
            document_id="d1",
            page=7,
            bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2},
            preview="Google prevents smartphone manufacturers from developing alternative Android versions",
        ),
        CitationRef(
            index=15,
            chunk_id="c15",
            document_id="d1",
            page=7,
            bbox={"x0": 0.1, "y0": 0.1, "x1": 0.9, "y1": 0.2},
            preview="Google prevents smartphone manufacturers from developing alternative Android versions",
        ),
    ]
    cmap = CitationMap(
        refs=refs,
        chunk_id_to_index={"c6": 6, "c15": 15},
        bundle_chunk_ids={},
    )
    answer = (
        "They claim Google restricts alternative Android devices [6][15]."
    )
    cleaned, validation = validate_response(answer, cmap, intent="case_overview")
    assert "[15]" not in cleaned
    assert "[6]" in cleaned
    assert validation.markers_reassigned == 1


def test_validate_response_reassigns_case_overview_to_best_chunk_preview():
    refs = [
        CitationRef(
            index=1,
            chunk_id="party",
            document_id="d1",
            page=1,
            bbox={"x0": 0.2, "y0": 0.7, "x1": 0.8, "y1": 0.8},
            preview="Google India Private Limited Opposite Party No. 2",
            pinpoint_quote="Google India Private Limited",
        ),
        CitationRef(
            index=2,
            chunk_id="court",
            document_id="d1",
            page=1,
            bbox={"x0": 0.2, "y0": 0.1, "x1": 0.8, "y1": 0.15},
            preview="Case No. 39 of 2018 Competition Commission of India",
            pinpoint_quote="Case No. 39 of 2018",
        ),
    ]
    cmap = CitationMap(
        refs=refs,
        chunk_id_to_index={"party": 1, "court": 2},
        bundle_chunk_ids={},
    )
    answer = (
        "## Court & citation\n"
        "The case is before the Competition Commission of India, Case No. 39 of 2018 [1]."
    )
    cleaned, validation = validate_response(answer, cmap, intent="case_overview")
    assert "[2]" in cleaned
    assert validation.markers_reassigned == 1


def test_validate_response_preserves_markdown_for_listing_intent():
    hits = [_hit("c1"), _hit("c2")]
    cmap = build_citation_map(hits)
    answer = (
        "## Summary\n"
        "Overview line [1].\n\n"
        "## doc.pdf\n"
        "Parties: A vs B [1].\n"
        "Forum: CCI [2].\n"
        "- Allegation one [1].\n"
        "- Allegation two [2].\n"
    )
    cleaned, validation = validate_response(answer, cmap, intent="entity_matter_listing")
    assert "Parties: A vs B [1].\nForum: CCI [2]." in cleaned
    assert cleaned.count("\n") >= answer.count("\n") - 1
    assert validation.markers_reassigned == 0


def test_validate_response_still_collapses_prose_without_listing_intent():
    hits = [_hit("c1"), _hit("c2")]
    cmap = build_citation_map(hits)
    answer = "First claim [1].\nSecond claim [2]."
    cleaned, _ = validate_response(answer, cmap)
    assert "\n" not in cleaned or cleaned == "First claim [1]. Second claim [2]."


def test_fact_verifier_strips_unsupported_amount():
    hit = SearchHit(
        chunk_id="c1",
        document_id="d1",
        page_number=1,
        text_content="The court discussed procedure only.",
        heading_path=None,
        bbox=None,
        score=1.0,
    )
    cmap = build_citation_map([hit], excerpt_chars=200)
    cmap.refs[0].preview = "The court discussed procedure only."
    answer = "Damages were £9,999,999 [1]."
    cleaned, validation = validate_response(answer, cmap)
    assert "9,999,999" not in cleaned
    assert validation.facts_stripped >= 1


def test_factual_lookup_prompt_uses_markdown_answer_section():
    text = (
        "get under the railing. The plaintiff's son, aged seven and a half "
        "years, was playing near the excavation."
    )
    hit = SearchHit(
        chunk_id="c-age",
        document_id="d1",
        page_number=6,
        text_content=text,
        heading_path=None,
        bbox=None,
        score=1.0,
    )
    cmap = build_citation_map([hit], excerpt_chars=600)
    prompt = build_system_prompt(
        cmap,
        intent="factual_lookup",
        sub_questions=[SubQuestion(label="son_name", question="Name?", fts_terms=["a", "b"])],
    )
    assert "## Answer" in prompt
    assert "Excerpt:" in prompt
    assert "Pinpoint:" not in prompt


def test_validate_response_reassigns_listing_intent_to_best_chunk_preview():
    refs = [
        CitationRef(
            index=1,
            chunk_id="party",
            document_id="d1",
            page=1,
            bbox={"x0": 0.2, "y0": 0.7, "x1": 0.8, "y1": 0.8},
            preview="Google India Private Limited Opposite Party No. 2",
            pinpoint_quote="Google India Private Limited",
        ),
        CitationRef(
            index=2,
            chunk_id="court",
            document_id="d1",
            page=1,
            bbox={"x0": 0.2, "y0": 0.1, "x1": 0.8, "y1": 0.15},
            preview="Case No. 39 of 2018 Competition Commission of India",
            pinpoint_quote="Case No. 39 of 2018",
        ),
    ]
    cmap = CitationMap(
        refs=refs,
        chunk_id_to_index={"party": 1, "court": 2},
        bundle_chunk_ids={},
    )
    answer = (
        "## 3920181652264686.pdf\n"
        "Forum: Competition Commission of India, Case No. 39 of 2018 [1]."
    )
    cleaned, validation = validate_response(answer, cmap, intent="entity_matter_listing")
    assert "[2]" in cleaned
    assert validation.markers_reassigned == 1


def test_validate_response_keeps_marker_in_same_document_for_listing():
    """Cross-document refs must not steal markers when intent is structured listing."""
    refs = [
        CitationRef(
            index=1,
            chunk_id="d1_caption",
            document_id="d1",
            page=1,
            bbox=None,
            preview="686.pdf — caption page mentioning Google India Private Limited",
            page_chunks=[
                {"chunk_id": "d1_caption", "text": "686.pdf caption with Google India Private Limited", "page": 1},
            ],
        ),
        CitationRef(
            index=2,
            chunk_id="d2_better",
            document_id="d2",
            page=1,
            bbox=None,
            preview=(
                "Case No. 39 of 2018 Competition Commission of India — "
                "this preview happens to overlap the claim more strongly"
            ),
            page_chunks=[
                {
                    "chunk_id": "d2_better",
                    "text": (
                        "Case No. 39 of 2018 Competition Commission of India — "
                        "this preview happens to overlap the claim more strongly"
                    ),
                    "page": 1,
                },
            ],
        ),
        CitationRef(
            index=3,
            chunk_id="d1_body",
            document_id="d1",
            page=2,
            bbox=None,
            preview="Forum: Competition Commission of India, Case No. 39 of 2018",
            page_chunks=[
                {
                    "chunk_id": "d1_body",
                    "text": "Forum: Competition Commission of India, Case No. 39 of 2018",
                    "page": 2,
                },
            ],
        ),
    ]
    cmap = CitationMap(
        refs=refs,
        chunk_id_to_index={"d1_caption": 1, "d2_better": 2, "d1_body": 3},
        bundle_chunk_ids={},
    )
    answer = (
        "## 686.pdf\n"
        "Forum: Competition Commission of India, Case No. 39 of 2018 [1]."
    )
    cleaned, validation = validate_response(
        answer, cmap, intent="entity_matter_listing",
    )
    assert "[2]" not in cleaned
    assert "[3]" in cleaned or "[1]" in cleaned


def test_references_for_api_cited_only_filters_and_orders():
    hits = [_hit("c1"), _hit("c2"), _hit("c3")]
    cmap = build_citation_map(hits)
    answer = "Alpha [1] then gamma [3]."
    refs = references_for_api(cmap, answer=answer, cited_only=True)
    assert len(refs) == 2
    assert [r["index"] for r in refs] == [1, 3]


def test_references_for_api_without_cited_only_returns_all():
    hits = [_hit("c1"), _hit("c2")]
    cmap = build_citation_map(hits)
    refs = references_for_api(cmap, answer="Only [1].", cited_only=False)
    assert len(refs) == 2


def test_validate_response_aligns_query_misspelling_to_source_case_name():
    preview = (
        "The court cited Owens v Liverpool Corporation as stronger authority on nervous shock "
        "when a mother witnesses the death of her child [11]."
    )
    cmap = CitationMap(
        refs=[
            CitationRef(
                index=11,
                chunk_id="c11",
                document_id="chester",
                page=32,
                bbox=None,
                preview=preview,
            ),
        ],
        chunk_id_to_index={"c11": 11},
        bundle_chunk_ids={},
    )
    query = "Summarize every passage discussing Ovens v Liverpool"
    answer = (
        "The court referenced Ovens v Liverpool Corporation to support liability for nervous shock [11]."
    )
    cleaned, _ = validate_response(
        answer, cmap, intent="case_overview", query=query,
    )
    assert "Ovens" not in cleaned
    assert "Owens v Liverpool Corporation" in cleaned
    assert "Note:" in cleaned
    assert "not the spelling used in your query" in cleaned
