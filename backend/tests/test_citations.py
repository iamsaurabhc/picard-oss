from app.schemas import ContextBundleOut, SearchHit
from app.services.citations import (
    build_citation_map,
    build_system_prompt,
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
