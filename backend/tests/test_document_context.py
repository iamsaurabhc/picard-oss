from unittest.mock import MagicMock

from app.services.document_context import DocumentContext, build_document_context


def test_document_context_prompt_includes_parties():
    ctx = DocumentContext(doc_type="msa", parties=["Alpha LLC", "Beta Inc"])
    block = ctx.to_prompt_block()
    assert "msa" in block.casefold()
    assert "Alpha LLC" in block


def test_build_document_context_empty_without_docs():
    ctx = build_document_context(MagicMock(), workspace_id="ws", document_ids=[])
    assert ctx.document_ids == []
