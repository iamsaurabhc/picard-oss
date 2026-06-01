from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from app.services.pdf_text_profile import analyze_pdf_text_layer
from app.services.parse_plan import build_parse_plan


def _make_text_pdf(path: Path, pages: int = 2) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    for i in range(pages):
        c.drawString(72, 720, f"Contract page {i + 1} with enough native text for detection.")
        c.showPage()
    c.save()


def test_analyze_digital_pdf(tmp_path):
    pdf = tmp_path / "digital.pdf"
    _make_text_pdf(pdf)
    profile = analyze_pdf_text_layer(pdf)
    assert profile.text_source == "digital"
    assert profile.pages_with_text == 2


def test_build_parse_plan_digital_disables_ocr(tmp_path):
    pdf = tmp_path / "digital.pdf"
    _make_text_pdf(pdf)
    plan = build_parse_plan(str(pdf))
    assert plan.text_source == "digital"
    assert plan.ocr_enabled is False
    assert plan.ocr_engine == "none"
