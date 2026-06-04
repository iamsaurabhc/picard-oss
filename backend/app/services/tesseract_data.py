"""Ensure Tesseract traineddata is available for liteparse OCR (desktop + dev)."""

from __future__ import annotations

import logging
import os
import shutil
import sys
import urllib.request
from pathlib import Path

from app.paths import resolve_picard_data_dir

logger = logging.getLogger(__name__)

# tessdata_fast: smaller, good default for desktop bundles (~4 MB for eng).
_TESSDATA_BASE = "https://github.com/tesseract-ocr/tessdata_fast/raw/refs/heads/main"


def tessdata_dir(data_dir: Path | None = None) -> Path:
    return (data_dir or resolve_picard_data_dir()) / "tessdata"


def _bundled_tessdata_dir() -> Path | None:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "tessdata"
        if (candidate / "eng.traineddata").is_file():
            return candidate
    vendor = Path(__file__).resolve().parents[2] / "vendor" / "tessdata"
    if (vendor / "eng.traineddata").is_file():
        return vendor
    return None


def _download_traineddata(language: str, dest: Path) -> None:
    url = f"{_TESSDATA_BASE}/{language}.traineddata"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".traineddata.part")
    logger.info("Downloading Tesseract data %s from %s", language, url)
    urllib.request.urlretrieve(url, tmp)  # noqa: S310 — fixed GitHub URL
    tmp.replace(dest)


def ensure_tesseract_data(
    data_dir: Path | None = None,
    *,
    language: str | None = None,
) -> Path:
    """
    Populate PICARD_DATA_DIR/tessdata and set TESSDATA_PREFIX for liteparse/tesseract-rs.
    Returns the tessdata directory containing *.traineddata files.
    """
    lang = language
    if not lang:
        try:
            from app.config import settings

            lang = settings.liteparse_ocr_language
        except Exception:
            lang = "eng"
    lang = (lang or "eng").strip() or "eng"
    dest_dir = tessdata_dir(data_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"{lang}.traineddata"

    if not target.is_file():
        bundled = _bundled_tessdata_dir()
        bundled_file = bundled / f"{lang}.traineddata" if bundled else None
        if bundled_file and bundled_file.is_file():
            shutil.copy2(bundled_file, target)
        else:
            _download_traineddata(lang, target)

    # tesseract-rs opens $TESSDATA_PREFIX/<lang>.traineddata (prefix is the tessdata folder).
    os.environ["TESSDATA_PREFIX"] = str(dest_dir.resolve())
    return dest_dir


def tesseract_ready(data_dir: Path | None = None, *, language: str | None = None) -> bool:
    lang = language
    if not lang:
        try:
            from app.config import settings

            lang = settings.liteparse_ocr_language
        except Exception:
            lang = "eng"
    lang = (lang or "eng").strip() or "eng"
    return (tessdata_dir(data_dir) / f"{lang}.traineddata").is_file()
