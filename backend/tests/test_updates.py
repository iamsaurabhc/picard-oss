from app.version import is_version_newer, normalize_version, read_version


def test_normalize_version_strips_v_prefix():
    assert normalize_version("v0.2.1") == "0.2.1"
    assert normalize_version(" 0.2.1 ") == "0.2.1"


def test_is_version_newer_only_when_strictly_ahead():
    assert is_version_newer("0.2.1", "0.2.0") is True
    assert is_version_newer("0.2.1", "0.2.1") is False
    assert is_version_newer("0.2.1", "v0.2.1") is False
    assert is_version_newer("v0.2.2", "0.2.1") is True
    assert is_version_newer("0.2.0", "0.2.1") is False


def test_read_version_prefers_picard_version_env(monkeypatch):
    monkeypatch.setenv("PICARD_VERSION", "v0.2.1")
    assert read_version() == "0.2.1"
