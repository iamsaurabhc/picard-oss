import os
from pathlib import Path

from app.services.tesseract_data import ensure_tesseract_data, tesseract_ready


def test_ensure_tesseract_from_vendor(tmp_path, monkeypatch):
    monkeypatch.setenv("PICARD_DATA_DIR", str(tmp_path))
    vendor = Path(__file__).resolve().parents[1] / "vendor" / "tessdata"
    if not (vendor / "eng.traineddata").is_file():
        return  # built in CI via build_backend_sidecar.sh
    dest = ensure_tesseract_data(language="eng")
    assert (dest / "eng.traineddata").is_file()
    assert os.environ["TESSDATA_PREFIX"] == str(dest.resolve())
    assert tesseract_ready() is True
