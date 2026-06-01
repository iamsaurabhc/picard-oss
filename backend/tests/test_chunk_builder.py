from app.services.chunk_builder import _extract_lines_from_liteparse, build_chunks_from_pdf
from liteparse.types import ParsedPage, ParseResult, TextItem


def test_extract_lines_uses_page_num_not_line_counter():
    pages = [
        ParsedPage(
            page_num=1,
            width=612,
            height=792,
            text="a b",
            text_items=[
                TextItem(text="line one", x=10, y=10, width=50, height=12),
                TextItem(text="line two", x=10, y=30, width=50, height=12),
            ],
        ),
        ParsedPage(
            page_num=2,
            width=612,
            height=792,
            text="c",
            text_items=[TextItem(text="page two", x=10, y=10, width=50, height=12)],
        ),
    ]
    lines = _extract_lines_from_liteparse(ParseResult(pages=pages, text=""))
    assert [line.page_number for line in lines] == [1, 1, 2]


def test_build_chunks_page_count_matches_parser_pages(tmp_path):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    pdf_path = tmp_path / "five-page.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    for i in range(5):
        c.drawString(72, 720, f"Page {i + 1} — native text layer sample for digital PDF detection.")
        c.showPage()
    c.save()

    chunks, page_count, meta = build_chunks_from_pdf(str(pdf_path))
    assert page_count == 5
    assert meta["text_source"] == "digital"
    assert meta["ocr_engine"] == "none"
    assert max(c.page_number for c in chunks) <= 5
    assert min(c.page_number for c in chunks) >= 1
