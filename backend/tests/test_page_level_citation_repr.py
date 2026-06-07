import json
import uuid

from app.db.models import Chunk, Document, Workspace
from app.db.session import utc_now_iso
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


def _seed_multi_chunk_page(db_session, chunks: list[tuple[str, str, float]]) -> tuple[str, dict[str, str]]:
    """chunks: (chunk_id, text, y0) on page 1."""
    now = utc_now_iso()
    ws_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    db_session.add(
        Workspace(id=ws_id, name="test", matter_ref=None, created_at=now, updated_at=now)
    )
    db_session.add(
        Document(
            id=doc_id,
            workspace_id=ws_id,
            file_name="3920181652264686.pdf",
            local_path="3920181652264686.pdf",
            content_hash=str(uuid.uuid4()),
            parse_status="done",
            page_count=1,
            created_at=now,
        )
    )
    ids: dict[str, str] = {}
    for chunk_id, text, y0 in chunks:
        cid = str(uuid.uuid4())
        ids[chunk_id] = cid
        db_session.add(
            Chunk(
                id=cid,
                document_id=doc_id,
                page_number=1,
                chunk_type="paragraph",
                bbox_json=json.dumps({"x0": 0.1, "y0": y0, "x1": 0.9, "y1": y0 + 0.1}),
                text_content=text,
                heading_path="Body",
                section_key=chunk_id,
                token_count=40,
            )
        )
    db_session.commit()
    return doc_id, ids


def test_page_level_preview_uses_merged_page_excerpt(db_session):
    """Citation preview must reflect merged page text, not only the representative chunk."""
    party_line = "Mr. Aaqib Javeed filed the information before the Competition Commission of India."
    google_line = "Google India Private Limited Opposite Party No. 2 Registered Office Bangalore Karnataka"
    doc_id, ids = _seed_multi_chunk_page(
        db_session,
        [
            ("google", google_line, 0.5),
            ("party", party_line, 0.1),
        ],
    )
    merged = f"{party_line} {google_line}"
    hit = SearchHit(
        chunk_id=ids["google"],
        document_id=doc_id,
        page_number=1,
        text_content=merged,
        heading_path=None,
        bbox={"x0": 0.1, "y0": 0.5, "x1": 0.9, "y1": 0.6},
        score=1.0,
    )
    cmap = build_citation_map(
        [hit],
        page_level=True,
        db=db_session,
        intent="case_overview",
        question="Give case details involving Aaqib Javeed",
        excerpt_chars=800,
    )
    previews = " ".join(r.preview for r in cmap.refs)
    assert "aaqib" in previews.casefold()


def test_page_level_map_splits_multi_chunk_page_by_excerpt_binding(db_session):
    court_text = "Case No. 39 of 2018 Competition Commission of India"
    party_text = "Google India Private Limited Opposite Party No. 2 Registered Office Bangalore"
    allegation_text = "Alleged contravention of Section 4 of the Competition Act 2002"
    doc_id, ids = _seed_multi_chunk_page(
        db_session,
        [
            ("court", court_text, 0.1),
            ("party", party_text, 0.5),
            ("allegation", allegation_text, 0.7),
        ],
    )
    merged = f"{court_text} {party_text} {allegation_text}"
    hit = SearchHit(
        chunk_id=ids["party"],
        document_id=doc_id,
        page_number=1,
        text_content=merged,
        heading_path=None,
        bbox={"x0": 0.1, "y0": 0.5, "x1": 0.9, "y1": 0.6},
        score=1.0,
    )
    cmap = build_citation_map(
        [hit],
        page_level=True,
        db=db_session,
        intent="case_overview",
        question="Give case details involving Aaqib Javeed",
        excerpt_chars=800,
    )
    assert len(cmap.refs) >= 2
    previews = " ".join(r.preview for r in cmap.refs)
    assert "Case No. 39" in previews
    assert "Google India" in previews
    court_ref = next(r for r in cmap.refs if "Case No. 39" in (r.preview or ""))
    assert court_ref.bbox is not None
    assert court_ref.bbox["y0"] == 0.1
    assert court_ref.page_chunks is not None
    assert len(court_ref.page_chunks) >= 2


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
