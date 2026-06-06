"""Citation Kernel unit tests (Phase 7.0 — CK-01–CK-04)."""

from __future__ import annotations

import asyncio
import re
from unittest.mock import AsyncMock, MagicMock, patch

from app.schemas import SearchHit
from app.services.citation_kernel import (
    enforce_cite_from_maps,
    merge_evidence_maps,
    run_corpus_evidence_step,
)
from app.services.citations import build_citation_map


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


def test_ck01_kernel_refuse_empty_hits_no_synthesis():
    """CK-01: empty hits → refused=True, stream_completion not called."""
    db = MagicMock()

    async def _run():
        with patch(
            "app.services.citation_kernel.stream_completion",
            new_callable=AsyncMock,
        ) as mock_stream:
            result = await run_corpus_evidence_step(
                db,
                "ws-1",
                "What is the liability cap?",
                hits=[],
                synthesize=True,
            )
        assert result.refused is True
        assert result.references == []
        mock_stream.assert_not_called()

    asyncio.run(_run())


def test_ck02_kernel_map_integrity():
    """CK-02: synthesized [N] markers resolve via chunk_id_to_index."""
    db = MagicMock()
    hits = [_hit("c1"), _hit("c2")]
    doc_names = {"d1": "Doc.pdf"}

    async def fake_stream(*args, **kwargs):
        yield "Claim one [1] and two [2]."

    async def _run():
        with patch(
            "app.services.citation_kernel.stream_completion",
            side_effect=fake_stream,
        ):
            from app.services.query_understanding import QueryUnderstanding

            understanding = QueryUnderstanding(
                intent="general",
                retrieval_mode="SIMPLE",
                search_passes=[],
                constraints=[],
                sub_questions=[],
                coverage_goal="",
                used_llm=False,
            )
            return await run_corpus_evidence_step(
                db,
                "ws-1",
                "Summarize liability.",
                hits=hits,
                understanding=understanding,
                doc_names=doc_names,
            )

    result = asyncio.run(_run())
    assert not result.refused
    assert "[1]" in result.content
    assert "[2]" in result.content
    for m in re.findall(r"\[(\d+)\]", result.content):
        idx = int(m)
        assert idx in {r.index for r in result.citation_map.refs}
        assert result.citation_map.chunk_id_to_index


def test_ck03_merge_evidence_maps_renumbers():
    """CK-03: two step maps with local [1] → global [1] and [2]."""
    cmap_a = build_citation_map([_hit("c1")], doc_names={"d1": "A.pdf"})
    cmap_b = build_citation_map([_hit("c2", doc_id="d2")], doc_names={"d2": "B.pdf"})
    merged, renumbered = merge_evidence_maps(
        [
            (cmap_a, "Role [1] here."),
            (cmap_b, "Other [1] there."),
        ]
    )
    assert len(merged.refs) == 2
    assert merged.refs[0].index == 1
    assert merged.refs[1].index == 2
    assert renumbered[0] == "Role [1] here."
    assert renumbered[1] == "Other [2] there."


def test_ck04_enforce_cite_from_maps_strips_unknown():
    """CK-04: [99] stripped when not in allowed maps."""
    cmap = build_citation_map([_hit("c1")])
    cleaned = enforce_cite_from_maps("See [1] and [99].", [cmap])
    assert "[1]" in cleaned
    assert "[99]" not in cleaned
