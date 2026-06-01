from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PageTextStats:
    page_number: int
    char_count: int


@dataclass(frozen=True)
class PdfTextProfile:
    page_count: int
    pages: tuple[PageTextStats, ...]
    total_chars: int
    pages_with_text: int

    @property
    def text_source(self) -> str:
        """digital | scanned | mixed"""
        if self.page_count == 0:
            return "unknown"
        if self.pages_with_text == 0:
            return "scanned"
        if self.pages_with_text >= self.page_count:
            return "digital"
        return "mixed"

    def to_dict(self) -> dict:
        return {
            "page_count": self.page_count,
            "total_chars": self.total_chars,
            "pages_with_text": self.pages_with_text,
            "text_source": self.text_source,
            "per_page_chars": [p.char_count for p in self.pages],
        }


def analyze_pdf_text_layer(
    pdf_path: str | Path,
    *,
    min_chars_per_page: int = 40,
    max_pages: int | None = None,
) -> PdfTextProfile:
    """Estimate whether a PDF has a usable native text layer (no OCR)."""
    from pypdf import PdfReader

    path = Path(pdf_path)
    reader = PdfReader(str(path))
    pages = reader.pages
    if max_pages is not None:
        pages = pages[:max_pages]

    stats: list[PageTextStats] = []
    pages_with_text = 0
    total_chars = 0
    for idx, page in enumerate(pages, start=1):
        text = (page.extract_text() or "").strip()
        char_count = len(text)
        stats.append(PageTextStats(page_number=idx, char_count=char_count))
        total_chars += char_count
        if char_count >= min_chars_per_page:
            pages_with_text += 1

    return PdfTextProfile(
        page_count=len(reader.pages),
        pages=tuple(stats),
        total_chars=total_chars,
        pages_with_text=pages_with_text,
    )
