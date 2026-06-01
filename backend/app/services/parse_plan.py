from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

from app.config import settings
from app.services.pdf_text_profile import PdfTextProfile, analyze_pdf_text_layer


@dataclass(frozen=True)
class ParsePlan:
    text_source: str
    ocr_enabled: bool
    ocr_engine: str
    ocr_server_url: str | None
    ocr_language: str
    dpi: float
    profile: PdfTextProfile
    paddleocr_reachable: bool | None

    def to_dict(self) -> dict:
        return {
            "text_source": self.text_source,
            "ocr_enabled": self.ocr_enabled,
            "ocr_engine": self.ocr_engine,
            "ocr_language": self.ocr_language,
            "dpi": self.dpi,
            "ocr_server_url": self.ocr_server_url,
            "paddleocr_reachable": self.paddleocr_reachable,
            "profile": self.profile.to_dict(),
        }


def _paddle_health_url(ocr_server_url: str) -> str:
    parsed = urlparse(ocr_server_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    return urljoin(base + "/", "health")


def check_paddleocr_server(ocr_server_url: str, *, timeout: float = 2.0) -> bool:
    try:
        health_url = _paddle_health_url(ocr_server_url)
        with httpx.Client(timeout=timeout) as client:
            res = client.get(health_url)
            if res.status_code != 200:
                return False
            data = res.json()
            return data.get("status") == "healthy"
    except Exception:
        return False


def build_parse_plan(pdf_path: str) -> ParsePlan:
    profile = analyze_pdf_text_layer(
        pdf_path,
        min_chars_per_page=settings.liteparse_min_chars_per_page,
    )
    text_source = profile.text_source

    if text_source == "digital":
        return ParsePlan(
            text_source=text_source,
            ocr_enabled=False,
            ocr_engine="none",
            ocr_server_url=None,
            ocr_language=settings.liteparse_ocr_language,
            dpi=settings.liteparse_dpi_digital,
            profile=profile,
            paddleocr_reachable=None,
        )

    ocr_url = settings.liteparse_ocr_server_url
    paddle_ok: bool | None = None
    ocr_engine = "tesseract"
    ocr_server_url: str | None = None

    if ocr_url:
        paddle_ok = check_paddleocr_server(ocr_url)
        if paddle_ok:
            ocr_engine = "paddleocr"
            ocr_server_url = ocr_url
        elif settings.liteparse_require_paddleocr:
            raise RuntimeError(
                f"PaddleOCR server unreachable at {ocr_url}. "
                "Start it with: ./scripts/start-paddleocr.sh"
            )

    return ParsePlan(
        text_source=text_source,
        ocr_enabled=True,
        ocr_engine=ocr_engine,
        ocr_server_url=ocr_server_url,
        ocr_language=settings.liteparse_ocr_language,
        dpi=settings.liteparse_dpi_ocr,
        profile=profile,
        paddleocr_reachable=paddle_ok,
    )
