from app.services.retrieval_progress import (
    RetrievalProgressEmitter,
    consume_retrieval_generator,
    trim_snippet_text,
)


def test_yield_from_return_propagation():
    def inner():
        yield {"event": "progress"}
        return ([], {"ok": True})

    def outer():
        return (yield from inner())

    events, result = consume_retrieval_generator(outer())
    assert len(events) == 1
    assert result == ([], {"ok": True})


def test_trim_snippet_text():
    assert trim_snippet_text("hello world", max_chars=20) == "hello world"
    long = "a" * 150
    assert trim_snippet_text(long, max_chars=120).endswith("…")
    assert len(trim_snippet_text(long, max_chars=120)) == 120


def test_snippet_dedupe_and_limit():
    emitter = RetrievalProgressEmitter(doc_names={"doc1": "Contract.pdf"})

    class Hit:
        chunk_id = "c1"
        document_id = "doc1"
        page_number = 2
        text_content = "Limitation of liability shall not exceed damages."
        score = 1.0

    first = emitter.snippet_from_hit(Hit(), "anchor")
    second = emitter.snippet_from_hit(Hit(), "anchor")
    assert first is not None
    assert second is None
    assert first["document_name"] == "Contract.pdf"
    assert first["text"]
