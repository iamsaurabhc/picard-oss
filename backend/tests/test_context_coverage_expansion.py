from __future__ import annotations

from sqlalchemy import select

from app.config import settings
from app.db.models import Chunk
from app.schemas import SearchHit
from app.services.context_coverage import (
    apply_context_coverage,
    compute_coverage_report,
    expand_context_hits,
    sandwich_order_hits,
)
from app.services.query_understanding import QueryUnderstanding, SubQuestion


def _hit(chunk_id: str, doc_id: str, page: int, text: str, section_key: str | None = None) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        document_id=doc_id,
        page_number=page,
        text_content=text,
        heading_path=None,
        section_key=section_key,
        bbox=None,
        score=-5.0,
    )


def test_expand_adds_page_siblings(corpus_session):
    settings.enable_context_expansion = True
    row = corpus_session.scalars(
        select(Chunk).where(Chunk.page_number == 3).limit(1)
    ).first()
    if not row:
        return
    siblings = corpus_session.scalars(
        select(Chunk).where(
            Chunk.document_id == row.document_id,
            Chunk.page_number == row.page_number,
        )
    ).all()
    if len(siblings) < 2:
        return

    seed = _hit(row.id, row.document_id, row.page_number, row.text_content or "", row.section_key)
    expanded, diag = expand_context_hits(
        corpus_session,
        [seed],
        max_chunks=12,
        max_per_page=6,
    )
    assert diag["expanded"] is True
    assert len(expanded) > 1
    assert diag["expansion_added"] >= 1
    page_ids = {c.id for c in siblings}
    assert len({h.chunk_id for h in expanded} & page_ids) >= min(len(siblings), 3)


def test_sandwich_order_places_second_at_end():
    hits = [
        _hit("a", "d1", 1, "first"),
        _hit("b", "d1", 2, "second"),
        _hit("c", "d1", 3, "third"),
        _hit("d", "d1", 4, "fourth"),
    ]
    ordered = sandwich_order_hits(hits)
    assert ordered[0].chunk_id == "a"
    assert ordered[-1].chunk_id == "b"


def test_coverage_report_sub_questions():
    understanding = QueryUnderstanding(
        intent="factual_lookup",
        sub_questions=[
            SubQuestion(label="damages", question="amount?", fts_terms=["damages", "sum"]),
        ],
    )
    hits = [_hit("x", "d", 3, "claimed damages in the sum of £1,000")]
    report = compute_coverage_report(hits, understanding)
    assert report.sub_question_coverage.get("damages") == "x"


def test_apply_context_coverage_disabled_returns_ranked(corpus_session):
    settings.enable_context_expansion = False
    understanding = QueryUnderstanding(intent="general")
    ranked = [_hit("only", "doc", 1, "text")]
    out, diag = apply_context_coverage(
        corpus_session,
        ranked,
        understanding,
        query="test",
        workspace_id="ws",
        document_ids=None,
        top_k=4,
    )
    assert out == ranked
    assert diag.get("expanded") is False
