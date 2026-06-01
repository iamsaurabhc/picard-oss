from unittest.mock import patch

from app.services.parse_plan import build_parse_plan, check_paddleocr_server


def test_check_paddleocr_server_uses_health_endpoint():
    with patch("app.services.parse_plan.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.get.return_value.status_code = 200
        client.get.return_value.json.return_value = {"status": "healthy"}
        assert check_paddleocr_server("http://localhost:8829/ocr") is True
        client.get.assert_called_once_with("http://localhost:8829/health")


def test_scanned_pdf_uses_paddle_when_reachable(tmp_path, monkeypatch):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    from app.config import settings

    pdf = tmp_path / "empty-text.pdf"
    c = canvas.Canvas(str(pdf), pagesize=letter)
    c.showPage()
    c.save()

    monkeypatch.setattr(settings, "liteparse_min_chars_per_page", 25)
    monkeypatch.setattr(settings, "liteparse_ocr_server_url", "http://localhost:8829/ocr")
    with patch("app.services.parse_plan.check_paddleocr_server", return_value=True):
        plan = build_parse_plan(str(pdf))
    assert plan.text_source == "scanned"
    assert plan.ocr_enabled is True
    assert plan.ocr_engine == "paddleocr"
    assert plan.ocr_server_url == "http://localhost:8829/ocr"
