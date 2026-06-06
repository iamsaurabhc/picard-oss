"""Assert latency-related SQLite indexes exist after bootstrap."""

from sqlalchemy import text


def test_retrieval_latency_indexes(db_engine):
    expected = {
        "idx_page_entities_document",
        "idx_page_entities_doc_page",
        "idx_entity_mentions_doc_type",
        "idx_documents_ws_parse_status",
        "idx_chunks_document_id",
        "idx_chunk_embeddings_model",
        "idx_page_embeddings_workspace",
        "idx_page_embeddings_document",
        "idx_page_embeddings_doc_page",
    }
    with db_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index'")
        ).all()
    names = {r[0] for r in rows}
    missing = expected - names
    assert not missing, f"missing indexes: {sorted(missing)}"
