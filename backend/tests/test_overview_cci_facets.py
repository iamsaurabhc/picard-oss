"""CCI-style multi-page overview: facet pages, enrichment, and excerpt coverage."""

from __future__ import annotations

import json
import uuid

from app.config import settings
from app.db.models import Chunk, Document, Workspace
from app.db.session import utc_now_iso
from app.services.citations import build_citation_map
from app.services.entity_extraction import extract_entities_for_document
from app.services.entity_page_context import retrieve_overview_page_hits
from app.services.entity_page_chunks import chunks_from_entity_mentions, dedupe_hits_by_page, merge_search_hits
from app.services.hybrid_search import fuse_page_scores_rrf, vector_page_scores
from app.services.query_understanding import (
    QueryConstraint,
    QueryUnderstanding,
    TargetEntity,
    _apply_overview_fields,
    _is_case_overview_query,
    _overview_sub_questions_from_facets,
)


def _seed_multi_page_doc(db_session, ws_id: str, file_name: str, pages: list[str]) -> str:
    now = utc_now_iso()
    doc_id = str(uuid.uuid4())
    db_session.add(
        Document(
            id=doc_id,
            workspace_id=ws_id,
            file_name=file_name,
            local_path=file_name,
            content_hash=str(uuid.uuid4()),
            parse_status="done",
            page_count=len(pages),
            created_at=now,
        )
    )
    for i, text in enumerate(pages, start=1):
        db_session.add(
            Chunk(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                page_number=i,
                chunk_type="paragraph",
                bbox_json=json.dumps({"x0": 0, "y0": 0, "x1": 1, "y1": 0.5}),
                text_content=text,
                heading_path="Body",
                section_key=f"s{i}",
                token_count=80,
            )
        )
    db_session.commit()
    extract_entities_for_document(db_session, doc_id)
    return doc_id


def _cci_understanding() -> QueryUnderstanding:
    q = "give case details filed by Purushottam Anand"
    u = QueryUnderstanding(intent="case_overview")
    u = _apply_overview_fields(u, q)
    u.sub_questions = _overview_sub_questions_from_facets()
    return u


def test_fuse_page_scores_rrf_combines_fts_and_vector():
    fts = {1: 10.0, 2: 5.0, 3: 1.0}
    vec = {4: 0.95, 2: 0.8, 5: 0.7}
    fused = fuse_page_scores_rrf(fts, vec)
    assert 2 in fused
    assert 4 in fused
    assert fused[4] > 0 or fused[2] > 0


def test_vector_page_scores_disabled_without_hybrid():
    settings.enable_hybrid_search = False
    assert vector_page_scores(
        None,  # type: ignore[arg-type]
        queries=["relief sought"],
        workspace_id="ws",
        document_ids=["doc"],
    ) == {}


def test_filed_by_query_intent_case_overview():
    settings.enable_regex_nlp = True
    assert _is_case_overview_query("give case details filed by Purushottam Anand")


def test_retrieve_overview_page_hits_includes_facet_pages(db_session):
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="CCI", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    db_session.commit()

    pages = [
        (
            "Information filed by Mr. Purushottam Anand and Mr. Kshitiz Arya. "
            "Case No. 1920201652249245 before the Competition Commission of India."
        ),
        "The informants allege contravention of Section 3 and Section 4 against Google LLC.",
        "Google licenses Android TV to smart TV OEMs in a manner similar to mobile phones.",
        "Google is dominant in app stores for smart TV operating systems.",
        "The informants pray for direction and penalty against the opposite parties.",
        "The relevant period of contravention extends from 2009 to 2018.",
        "The matter is under consideration by the Commission.",
    ]
    doc_id = _seed_multi_page_doc(db_session, ws.id, "1920201652249245.pdf", pages)

    u = _cci_understanding()
    u.target_entity = TargetEntity(
        canonical="purushottam anand",
        surfaces=["Purushottam Anand"],
        resolved_canonicals=["purushottam anand"],
    )
    u.constraints.append(
        QueryConstraint(type="party", canonical="purushottam anand", surfaces=["Purushottam Anand"])
    )

    hits, diag = retrieve_overview_page_hits(
        db_session,
        workspace_id=ws.id,
        document_id=doc_id,
        query="give case details filed by Purushottam Anand",
        understanding=u,
    )
    selected = diag.get("pages_selected") or []
    assert 1 in selected
    assert any(p >= 5 for p in selected), f"expected relief/date/outcome pages, got {selected}"
    assert diag.get("party_scoped_pages") is True

    merged_text = " ".join(h.text_content or "" for h in hits)
    assert "Competition Commission" in merged_text or any(
        "Commission" in (h.text_content or "") for h in hits
    )


def test_overview_page_context_enriches_entity_mentions(db_session):
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="CCI", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    db_session.commit()

    pages = [
        "Information filed by Purushottam Anand. Case No. 1920201652249245. Competition Commission of India.",
        "Allegations against Google LLC under the Competition Act 2002.",
        "Relief and penalty sought by the informants.",
    ]
    doc_id = _seed_multi_page_doc(db_session, ws.id, "1920201652249245.pdf", pages)

    hits, _ = retrieve_overview_page_hits(
        db_session,
        workspace_id=ws.id,
        document_id=doc_id,
        query="give case details filed by Purushottam Anand",
        understanding=_cci_understanding(),
    )
    entity_hits = chunks_from_entity_mentions(
        db_session,
        ws.id,
        [doc_id],
        entity_types=("amount", "party", "date", "identifier"),
        limit=20,
    )
    merged = dedupe_hits_by_page(merge_search_hits(hits, entity_hits))
    assert len(merged) >= 2


def test_overview_facet_excerpt_surfaces_cci_court_and_relief(db_session):
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="CCI", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    db_session.commit()

    pages = [
        (
            "Information filed by Mr. Purushottam Anand. Case No. 1920201652249245. "
            "Competition Commission of India."
        ),
        "Alleged contravention of Section 4 against Google LLC.",
        "The informants pray for direction and penalty against opposite parties.",
        "Relevant period from 2009 to 2018.",
        "Matter under investigation by the Commission.",
    ]
    doc_id = _seed_multi_page_doc(db_session, ws.id, "1920201652249245.pdf", pages)

    hits, _ = retrieve_overview_page_hits(
        db_session,
        workspace_id=ws.id,
        document_id=doc_id,
        query="give case details filed by Purushottam Anand",
        understanding=_cci_understanding(),
    )

    cmap = build_citation_map(
        hits,
        page_level=True,
        intent="case_overview",
        prefer_amounts=True,
        question="give case details filed by Purushottam Anand",
        sub_questions=_overview_sub_questions_from_facets(),
        excerpt_chars=settings.overview_excerpt_chars,
    )
    previews = " ".join(r.preview for r in cmap.refs)
    assert "Commission" in previews or "1920201652249245" in previews
    assert "relief" in previews.casefold() or "penalty" in previews.casefold() or "direction" in previews.casefold()
    assert "2009" in previews or "2018" in previews


def test_overview_expansive_excerpt_budget(db_session):
    now = utc_now_iso()
    ws = Workspace(id=str(uuid.uuid4()), name="CCI", matter_ref=None, created_at=now, updated_at=now)
    db_session.add(ws)
    db_session.commit()

    full_page = (
        "Information filed by Purushottam Anand before the Competition Commission of India. "
        "Case No. 1920201652249245. The informants allege contravention against Google LLC. "
        "They pray for direction and penalty. Relevant period 2009 to 2018. "
        "Matter under consideration."
    )
    doc_id = _seed_multi_page_doc(db_session, ws.id, "1920201652249245.pdf", [full_page])

    hit_pages, _ = retrieve_overview_page_hits(
        db_session,
        workspace_id=ws.id,
        document_id=doc_id,
        query="give case details filed by Purushottam Anand",
        understanding=_cci_understanding(),
    )
    cmap = build_citation_map(
        hit_pages,
        page_level=True,
        intent="case_overview",
        prefer_amounts=True,
        question="give case details filed by Purushottam Anand",
        sub_questions=_overview_sub_questions_from_facets(),
        excerpt_chars=settings.overview_excerpt_chars,
    )
    preview = cmap.refs[0].preview
    assert len(preview) >= 150
    assert "Commission" in preview
    assert "relief" in preview.casefold() or "penalty" in preview.casefold() or "direction" in preview.casefold()
