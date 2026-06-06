"""Agent memory tests (Phase 7a — AG-04)."""

from app.services.agent_memory import memory_store_allowed


def test_memory_store_rejects_citation_markers():
    assert memory_store_allowed("The cap is $1M [1] per section 4.") is False


def test_memory_store_rejects_ext_markers():
    assert memory_store_allowed("See [ext:2] for web source.") is False


def test_memory_store_allows_procedural_preference():
    assert memory_store_allowed("DD workflow: partner review before export.") is True


def test_memory_store_rejects_empty():
    assert memory_store_allowed("") is False
    assert memory_store_allowed("   ") is False
