from __future__ import annotations

import json

from sqlalchemy import select

from app.db.models import Chunk
from app.schemas import SearchRequest
from app.services.citations import references_for_api, refuse_gate
from app.services.chat_corpus_pipeline import retrieve_for_agent, run_chat_corpus_answer
from app.services.search import execute_search
from app.tools.context import ToolContext
from app.tools.response import tool_json


def bind_corpus_tools(ctx: ToolContext) -> list:
    tools = []

    def search_corpus(query: str) -> str:
        body = ctx.stream_request(query)
        retrieval = retrieve_for_agent(ctx.db, body)
        if refuse_gate(retrieval.hits) and not retrieval.listing_map_result:
            ctx.emit({"event": "step_refused", "tool": "search_corpus", "query": query})
            return tool_json(refused=True, content="No relevant information was found in the selected documents.")
        top = retrieval.hits[:12]
        discovered = retrieval.retrieval_diagnostics.get("document_ids_discovered") or []
        doc_ids_from_hits = sorted({h.document_id for h in retrieval.hits})
        document_ids = discovered or doc_ids_from_hits
        payload = {
            "summary": f"Retrieved {len(retrieval.hits)} chunks (showing {len(top)}).",
            "document_ids": document_ids,
            "documents_discovered": len(document_ids),
            "chunk_ids": [h.chunk_id for h in top],
            "snippets": [
                {
                    "chunk_id": h.chunk_id,
                    "document_id": h.document_id,
                    "page": h.page_number,
                    "preview": (h.text_content or "")[:400],
                    "score": h.score,
                }
                for h in top
            ],
        }
        return tool_json(
            refused=False,
            content=json.dumps(payload),
            references=[],
            diagnostics=retrieval.retrieval_diagnostics,
        )

    search_corpus.tool_info = {
        "name": "search_corpus",
        "description": (
            "Search vault for relevant excerpts. Returns document_ids (multi-matter scope), "
            "chunk_ids, and previews. Use read_chunks only with chunk_ids from this result; "
            "for holistic legal questions prefer answer_from_corpus."
        ),
    }
    tools.append(search_corpus)

    def answer_from_corpus(question: str) -> str:
        import asyncio

        body = ctx.stream_request(question)

        async def _run():
            return await run_chat_corpus_answer(ctx.db, body)

        try:
            asyncio.get_running_loop()
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(lambda: asyncio.run(_run())).result()
        except RuntimeError:
            result = asyncio.run(_run())

        if result.refused:
            ctx.emit({"event": "step_refused", "tool": "answer_from_corpus", "query": question})
            return tool_json(refused=True, content=result.content)
        refs = references_for_api(result.citation_map)
        if refs:
            ctx.emit(
                {
                    "event": "references",
                    "references": refs,
                    "citation_validation": {},
                }
            )
        return tool_json(refused=False, content=result.content, references=refs)

    answer_from_corpus.tool_info = {
        "name": "answer_from_corpus",
        "description": (
            "Required for vault Q&A: returns a fully cited markdown answer (same Citation Kernel as Chat). "
            "Call this for listing, overview, and factual questions before attempting manual synthesis."
        ),
    }
    tools.append(answer_from_corpus)

    def read_chunks(chunk_ids_json: str) -> str:
        try:
            chunk_ids = json.loads(chunk_ids_json)
        except json.JSONDecodeError:
            chunk_ids = [chunk_ids_json]
        if not isinstance(chunk_ids, list):
            chunk_ids = [str(chunk_ids)]
        rows = ctx.db.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids))).all()
        snippets = [
            {"chunk_id": c.id, "page": c.page_number, "text": (c.text_content or "")[:500]}
            for c in rows
        ]
        return tool_json(refused=False, content=json.dumps(snippets), tier="A")

    read_chunks.tool_info = {
        "name": "read_chunks",
        "description": (
            "Load chunk text by id (JSON array of chunk_ids from search_corpus). "
            "After reading chunks you MUST call answer_from_corpus to produce a cited answer."
        ),
    }
    tools.append(read_chunks)

    return tools
