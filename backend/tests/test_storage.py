from pathlib import Path

from app.services.storage import hash_bytes, resolve_pdf_path, save_pdf


def test_hash_bytes_stable():
    assert hash_bytes(b"abc") == hash_bytes(b"abc")
    assert hash_bytes(b"abc") != hash_bytes(b"abcd")


def test_save_and_resolve_pdf(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "picard_data_dir", tmp_path)
    rel, digest = save_pdf("ws1", "doc1", b"%PDF-1.4 test")
    assert digest
    path = resolve_pdf_path(rel)
    assert path.exists()


def test_path_traversal_rejected(tmp_path, monkeypatch):
    from app.config import settings
    import pytest
    from fastapi import HTTPException

    monkeypatch.setattr(settings, "picard_data_dir", tmp_path)
    with pytest.raises(HTTPException):
        resolve_pdf_path("../outside.pdf")
