"""PyInstaller entrypoint for the Picard desktop backend sidecar."""
import multiprocessing
import os
import sys
import traceback
from pathlib import Path

import uvicorn


def _log(msg: str) -> None:
    data_dir = os.environ.get(
        "PICARD_DATA_DIR",
        os.path.expanduser("~/Library/Application Support/Picard"),
    )
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "desktop-backend.log")
    with open(path, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def _configure_tesseract() -> None:
    try:
        from app.services.tesseract_data import ensure_tesseract_data

        lang = os.environ.get("LITEPARSE_OCR_LANGUAGE", "eng")
        dest = ensure_tesseract_data(language=lang)
        _log(f"tesseract configured tessdata={dest}")
    except Exception:
        _log(f"tesseract setup failed\n{traceback.format_exc()}")


def _configure_tiktoken_cache() -> None:
    """Offline tiktoken BPE tables for litellm (OpenAI cl100k_base)."""
    if not getattr(sys, "frozen", False):
        return
    base = Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    cache = base / "tiktoken_cache"
    if cache.is_dir():
        os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(cache))


def _configure_pdfium() -> None:
    """Point liteparse/pdfium-rs at the bundled dylib inside the PyInstaller onedir."""
    if not getattr(sys, "frozen", False):
        return
    base = Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    for name in ("libpdfium.dylib", "libpdfium.so", "pdfium.dll"):
        candidate = base / "liteparse" / name
        if candidate.is_file():
            os.environ.setdefault("PDFIUM_LIB_PATH", str(candidate.parent))
            _log(f"pdfium configured path={candidate.parent}")
            return
    _log("pdfium WARNING: bundled libpdfium not found")


def main() -> None:
    if getattr(sys, "frozen", False):
        os.chdir(os.path.dirname(sys.executable))
        _configure_pdfium()
        _configure_tiktoken_cache()
    _configure_tesseract()
    _log(f"starting backend cwd={os.getcwd()}")
    try:
        import litellm.litellm_core_utils.tokenizers  # noqa: F401

        _log("litellm tokenizers import ok")
    except Exception as exc:
        _log(f"litellm tokenizers import failed: {exc}")
    from app.main import app

    config = uvicorn.Config(
        app,
        host=os.environ.get("BACKEND_HOST", "127.0.0.1"),
        port=int(os.environ.get("BACKEND_PORT", "8000")),
        log_level=os.environ.get("LOG_LEVEL", "info"),
        loop="asyncio",
        reload=False,
    )
    uvicorn.Server(config).run()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        main()
    except Exception:
        _log(traceback.format_exc())
        raise
