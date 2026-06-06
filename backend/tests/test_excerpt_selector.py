import json
from unittest.mock import patch

from app.config import settings
from app.services.excerpt_selector import (
    _amount_anchored_excerpt,
    _best_excerpt,
    _fallback_excerpt,
    overview_facet_excerpt,
    select_excerpts,
)
from app.schemas import SearchHit


def _hit(text: str, chunk_id: str = "c1") -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        document_id="d1",
        page_number=2,
        text_content=text,
        heading_path=None,
        bbox=None,
        score=1.0,
    )


def test_fallback_excerpt_finds_age_span():
    settings.enable_excerpt_selector = False
    text = "header text. " + ("The plaintiff's son, aged seven years. " * 5)
    out = select_excerpts([_hit(text)], question="age?", max_chars=80)
    assert "aged seven" in out["c1"].casefold()


def test_excerpt_selector_mock_returns_fact_span():
    settings.enable_excerpt_selector = True
    text = (
        "v. Council citation header. "
        "Ma x Chester, the infant son of the plaintiff, fell into the drain."
    )
    payload = json.dumps({
        "excerpts": [{
            "chunk_id": "c1",
            "excerpt": "Ma x Chester, the infant son of the plaintiff, fell into the drain.",
            "start_offset": 30,
        }],
    })
    with patch("app.services.excerpt_selector.completion", return_value=payload):
        out = select_excerpts([_hit(text)], question="son's name?", max_chars=200)
    assert "infant son" in out["c1"].casefold()


def test_best_excerpt_surfaces_infant_son():
    text = (
        "v. Council of the Municipality of Waverley, (1938) 38 S.R. affirmed. "
        "Ma x Chester, the infant son of the plaintiff, fell into the drain."
    )
    excerpt = _best_excerpt(text, 200)
    assert "infant son" in excerpt.casefold()
    assert "ma x" in excerpt.casefold() or "chester" in excerpt.casefold()


def test_amount_anchored_excerpt_prefers_currency_over_generic_damage():
    text = (
        "The injury and damage claimed in the declaration was pleaded in general. "
        "The plaintiff claimed damages in the sum of £1,000 for nervous shock."
    )
    excerpt = _amount_anchored_excerpt(text, 300)
    assert excerpt
    assert "£1,000" in excerpt or "1,000" in excerpt


def test_overview_facet_excerpt_prefers_explicit_amount_over_generic_damage():
    from app.services.query_understanding import _overview_sub_questions_from_facets

    text = (
        "In the declaration the injury and damage claimed was pleaded in general terms. "
        "Ma x Chester, the infant son of the plaintiff, fell into the drain. "
        "The plaintiff claimed damages in the sum of £1,000."
    )
    excerpt = overview_facet_excerpt(
        text,
        1200,
        sub_questions=_overview_sub_questions_from_facets(),
    )
    assert excerpt
    assert "£1,000" in excerpt or "1,000" in excerpt


def test_overview_facet_excerpt_keeps_victim_and_damages():
    from app.services.query_understanding import _overview_sub_questions_from_facets

    text = (
        "Header citation v. Council of the Municipality of Waverley. "
        "Ma x Chester, the infant son of the plaintiff, fell into the drain and received "
        "injuries whereof he subsequently died. "
        "The plaintiff claimed damages in the sum of £1,000. "
        "The Full Court dismissed the appeal."
    )
    excerpt = overview_facet_excerpt(
        text,
        900,
        sub_questions=_overview_sub_questions_from_facets(),
    )
    assert excerpt
    lower = excerpt.casefold()
    assert "infant son" in lower
    assert "1,000" in excerpt or "£1,000" in excerpt
    assert "died" in lower or "injur" in lower


def test_best_excerpt_anchors_name_in_long_declaration():
    text = (
        "ess and was otherwise greatly damnified. In a second count, tendered at the "
        "commencement of the hearing of the action, the plaintiff alleged that the defendant "
        "so negligently created an excavation in a public highway and omitted to safeguard "
        "the excavation work and open drain Ma x Chester, the infant son of the plaintiff, "
        "fell into the drain and received injuries whereof he subsequently died."
    )
    excerpt = _best_excerpt(text, 600)
    assert "ma x" in excerpt.casefold() or "chester" in excerpt.casefold()
    assert "infant son" in excerpt.casefold()
