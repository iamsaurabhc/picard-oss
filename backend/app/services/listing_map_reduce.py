"""Per-document map-reduce synthesis for entity matter listing."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import settings
from app.prompts.legal_rag import contrastive_block_for_listing_phase, preamble_for_variant
from app.schemas import SearchHit
from app.services.carp import _load_page_chunks
from app.services.citations import (
    CitationMap,
    CitationRef,
    build_citation_map,
)
from app.services.document_context import build_document_context
from app.services.entity_index import (
    count_documents_for_party,
    lookup_pages_for_party_in_document,
)
from app.services.entity_page_chunks import (
    chunks_from_entity_mentions_per_doc,
    merge_search_hits,
)
from app.services.model_router import ModelRole, completion, stream_completion
from app.services.pass_retrieval import run_search_passes_for_document
from app.services.planned_retrieval import _fts_hit_to_search_hit
from app.services.query_understanding import QueryUnderstanding, SearchPass
from app.services.retrieval_progress import RetrievalProgressEmitter

_MARKER_RE = re.compile(r"\[(\d+)\]")


@dataclass
class ListingDocBrief:
    document_id: str
    file_name: str
    brief_markdown: str
    citation_map: CitationMap


def _canonicals_from_understanding(understanding: QueryUnderstanding) -> list[str]:
    target = understanding.target_entity
    if target and target.resolved_canonicals:
        return list(target.resolved_canonicals)
    if target:
        return [target.canonical]
    for c in understanding.constraints:
        if c.type == "party":
            return [c.canonical]
    return []


def _search_passes_for(understanding: QueryUnderstanding) -> list[SearchPass]:
    passes = list(understanding.search_passes)
    if passes:
        return passes
    terms = list(understanding.fts.must_terms[:2])
    if not terms and understanding.target_entity:
        terms = [
            t for t in understanding.target_entity.canonical.split() if len(t) > 2
        ][:2]
    if terms:
        return [
            SearchPass(label="entity_anchor", fts_terms=terms, operator="OR", pin_best=False)
        ]
    return []


def retrieve_hits_for_listing_document(
    db: Session,
    *,
    workspace_id: str,
    document_id: str,
    understanding: QueryUnderstanding,
    query: str,
    canonicals: list[str],
    chunks_per_doc: int | None = None,
) -> list[SearchHit]:
    """Per-document FTS passes, entity page seeds, and fair entity-mention chunks."""
    cap = chunks_per_doc or settings.chat_listing_map_chunks_per_doc
    search_passes = _search_passes_for(understanding)
    entity_pages = lookup_pages_for_party_in_document(
        db, workspace_id, document_id, canonicals,
    )
    page_hint = entity_pages or None
    pass_top_k = max(cap, 4)

    fts_hits = run_search_passes_for_document(
        db,
        workspace_id=workspace_id,
        document_id=document_id,
        query=query,
        search_passes=search_passes,
        anchor_plan=understanding.fts,
        page_hint=page_hint,
        pass_top_k=pass_top_k,
        max_chunks_per_doc=cap,
    )
    hits = [_fts_hit_to_search_hit(h) for h in fts_hits]

    if page_hint:
        for page in sorted(page_hint)[:6]:
            for ph in _load_page_chunks(db, document_id, page):
                hits = merge_search_hits(hits, [_fts_hit_to_search_hit(ph)])

    entity_hits = chunks_from_entity_mentions_per_doc(
        db,
        workspace_id,
        [document_id],
        per_doc_limit=cap,
    )
    hits = merge_search_hits(hits, entity_hits)

    seen: set[str] = set()
    capped: list[SearchHit] = []
    for h in sorted(hits, key=lambda x: x.score):
        if h.chunk_id in seen:
            continue
        seen.add(h.chunk_id)
        capped.append(h)
        if len(capped) >= cap:
            break
    return capped


def build_listing_map_prompt(
    citation_map: CitationMap,
    *,
    file_name: str,
    target_entity: str,
    metadata_block: str = "",
) -> str:
    preamble = preamble_for_variant(settings.prompt_variant)
    contrastive = contrastive_block_for_listing_phase("map")
    excerpt_cap = settings.chat_listing_map_excerpt_chars
    lines = [
        preamble,
        "",
        contrastive,
        "",
        "You are preparing a per-document matter brief for a legal listing.",
        f"Target party: {target_entity}",
        f"Document: {file_name}",
        "Answer ONLY using the source excerpts below.",
        "Output markdown bullets only (no ## heading):",
        "- **Role of party:** defendant/respondent/opposite party — only if stated [N]",
        "- **Other parties / counterparties:** informants, complainants, co-respondents [N]",
        "- **Forum / statute:** court, commission, act sections [N]",
        "- **Key facts:** who filed against whom, allegations, provisions [N]",
        "- **Outcome / stage:** disposition, order, stage, penalty — only if stated [N]",
        "",
        "Rules:",
        "- Every factual bullet MUST include inline [N] from Sources below.",
        "- Use citation numbers only from this document's Sources.",
        "- If excerpts are thin, write one bullet: 'Limited detail in retrieved excerpts' with any cite you have.",
        "- Do not invent citation numbers.",
    ]
    if metadata_block.strip():
        hint = (
            "Use tabular metadata above for structure"
            if "Tabular review metadata" in metadata_block
            else "Use indexed document metadata above for structure"
        )
        lines.extend([
            "",
            metadata_block.strip(),
            "",
            f"{hint}; cite factual claims only from Sources below with [N].",
        ])
    lines.append("Sources:")
    for ref in citation_map.refs:
        body = (ref.preview or "")[:excerpt_cap]
        doc_label = ref.document_name or ref.document_id
        lines.append(
            f"[{ref.index}] {doc_label} (page {ref.page})\n   Excerpt: \"{body}\""
        )
    return "\n".join(lines)


def build_listing_reduce_prompt(
    brief_sections: list[tuple[str, str]],
    *,
    target_entity: str,
    total_discovered: int,
    shown_count: int,
) -> str:
    preamble = preamble_for_variant(settings.prompt_variant)
    contrastive = contrastive_block_for_listing_phase("reduce")
    entity_label = target_entity or "the named party"
    coverage_note = ""
    if total_discovered > shown_count:
        coverage_note = (
            f"Discovered: {total_discovered} documents. "
            f"This answer covers the top {shown_count} by indexed prominence. "
            "State that clearly in the Summary."
        )
    else:
        coverage_note = (
            f"Discovered: {total_discovered} documents. "
            f"Include all {shown_count} in the answer."
        )

    lines = [
        preamble,
        "",
        contrastive,
        "",
        "You are synthesizing per-document matter briefs into a multi-document listing.",
        f"The user asked for all cases/matters involving {entity_label}.",
        coverage_note,
        "",
        "Structure:",
        "## Summary",
        f"One sentence: how many documents mention {entity_label} "
        "(use the discovered count above) and what kinds of proceedings they are.",
        "",
        "Then one markdown section per document brief below:",
        "## [Document filename exactly as given in the brief header]",
        "Paste the brief bullets under each heading; keep inline [N] citations unchanged.",
        "",
        "Rules:",
        "- Do NOT merge facts across documents into one narrative.",
        "- Do NOT re-interpret or add facts beyond the briefs.",
        "- Include every document brief below as its own ## section.",
        "- Keep citation markers [N] exactly as in the briefs.",
        "- Do not invent citation numbers.",
        "",
        "Per-document briefs:",
    ]
    for file_name, brief_md in brief_sections:
        lines.append(f"### Brief for: {file_name}")
        lines.append(brief_md.strip() or "- Limited detail in retrieved excerpts.")
        lines.append("")
    return "\n".join(lines)


def _renumber_markers(text: str, offset: int) -> str:
    def _repl(m: re.Match) -> str:
        return f"[{int(m.group(1)) + offset}]"

    return _MARKER_RE.sub(_repl, text)


def merge_listing_briefs(
    briefs: list[ListingDocBrief],
) -> tuple[list[tuple[str, str]], CitationMap]:
    """Combine per-doc briefs into global citation map and renumbered section text."""
    global_refs: list[CitationRef] = []
    chunk_to_index: dict[str, int] = {}
    sections: list[tuple[str, str]] = []

    for brief in briefs:
        offset = len(global_refs)
        for ref in brief.citation_map.refs:
            new_index = len(global_refs) + 1
            global_refs.append(
                CitationRef(
                    index=new_index,
                    chunk_id=ref.chunk_id,
                    document_id=ref.document_id,
                    page=ref.page,
                    bbox=ref.bbox,
                    preview=ref.preview,
                    bundle_id=ref.bundle_id,
                    document_name=ref.document_name,
                    heading_path=ref.heading_path,
                    pinpoint_quote=ref.pinpoint_quote,
                )
            )
            chunk_to_index[ref.chunk_id] = new_index

        section_body = _renumber_markers(brief.brief_markdown, offset)
        sections.append((brief.file_name, section_body))

    combined_map = CitationMap(
        refs=global_refs,
        chunk_id_to_index=chunk_to_index,
        bundle_chunk_ids={},
    )
    return sections, combined_map


def map_document_to_brief(
    db: Session,
    *,
    workspace_id: str,
    document_id: str,
    file_name: str,
    understanding: QueryUnderstanding,
    query: str,
    canonicals: list[str],
    doc_names: dict[str, str],
    tabular_review_id: str | None = None,
) -> ListingDocBrief:
    hits = retrieve_hits_for_listing_document(
        db,
        workspace_id=workspace_id,
        document_id=document_id,
        understanding=understanding,
        query=query,
        canonicals=canonicals,
    )
    meta_parts: list[str] = []
    if tabular_review_id:
        from app.services.tabular import build_tabular_document_metadata_block

        tabular_meta = build_tabular_document_metadata_block(
            db, tabular_review_id, document_id,
        )
        if tabular_meta:
            meta_parts.append(tabular_meta)
    doc_meta = build_document_context(
        db,
        workspace_id=workspace_id,
        document_ids=[document_id],
    ).to_prompt_block()
    if doc_meta and "No indexed metadata" not in doc_meta:
        meta_parts.append(
            doc_meta.replace(
                "Document context (use vocabulary from these excerpts when choosing FTS terms):",
                "Indexed document metadata:",
                1,
            )
        )
    meta = "\n\n".join(meta_parts)

    excerpt_chars = settings.chat_listing_map_excerpt_chars
    citation_map = build_citation_map(
        hits,
        None,
        doc_names=doc_names,
        excerpt_chars=excerpt_chars,
        question=query,
        sub_questions=understanding.sub_questions,
        prefer_listing=True,
        intent="entity_matter_listing",
        coverage_goal=understanding.coverage_goal,
        db=db,
        workspace_id=workspace_id,
    )
    target = (
        understanding.target_entity.canonical if understanding.target_entity else ""
    )
    prompt = build_listing_map_prompt(
        citation_map,
        file_name=file_name,
        target_entity=target,
        metadata_block=meta,
    )
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": query},
    ]
    raw = completion(messages=messages, role=ModelRole.SLM)
    brief_md = (raw or "").strip()
    if not brief_md:
        brief_md = "- Limited detail in retrieved excerpts."
    return ListingDocBrief(
        document_id=document_id,
        file_name=file_name,
        brief_markdown=brief_md,
        citation_map=citation_map,
    )


def should_use_listing_map_reduce(
    document_ids_discovered: list[str],
    *,
    enabled: bool | None = None,
    tabular_review_id: str | None = None,
    db: Session | None = None,
) -> bool:
    del tabular_review_id, db  # discovery union makes tabular optional; gate on doc count only
    use = settings.enable_listing_map_reduce if enabled is None else enabled
    return use and len(document_ids_discovered) >= 2


def run_listing_map_reduce_with_progress(
    db: Session,
    understanding: QueryUnderstanding,
    *,
    workspace_id: str,
    document_ids: list[str] | None,
    query: str,
    document_ids_discovered: list[str],
    documents_total_discovered: int | None = None,
    tabular_review_id: str | None = None,
    emitter: RetrievalProgressEmitter | None = None,
) -> Iterator[dict]:
    """Map each discovered document to a brief, then yield reduce-ready artifacts."""
    progress = emitter or RetrievalProgressEmitter()
    canonicals = _canonicals_from_understanding(understanding)
    if documents_total_discovered is not None and documents_total_discovered > 0:
        total_discovered = documents_total_discovered
    else:
        total_discovered = count_documents_for_party(
            db, workspace_id, canonicals, document_ids,
        )
        if total_discovered == 0:
            total_discovered = len(document_ids_discovered)

    max_map = settings.chat_listing_map_max_docs
    ordered = list(document_ids_discovered)[:max_map]
    doc_names = progress.doc_names

    yield progress.progress(
        "map",
        "start",
        documents_total=total_discovered,
        documents_to_map=len(ordered),
    )

    briefs: list[ListingDocBrief] = []
    for doc_id in ordered:
        file_name = doc_names.get(doc_id, doc_id)
        yield progress.progress(
            "map",
            "start",
            document_id=doc_id,
            document_name=file_name,
        )
        brief = map_document_to_brief(
            db,
            workspace_id=workspace_id,
            document_id=doc_id,
            file_name=file_name,
            understanding=understanding,
            query=query,
            canonicals=canonicals,
            doc_names=doc_names,
            tabular_review_id=tabular_review_id,
        )
        briefs.append(brief)
        yield progress.progress(
            "map",
            "done",
            document_id=doc_id,
            document_name=file_name,
            chunk_count=len(brief.citation_map.refs),
        )

    yield progress.progress("map", "done", brief_count=len(briefs))

    section_pairs, citation_map = merge_listing_briefs(briefs)
    target = (
        understanding.target_entity.canonical if understanding.target_entity else None
    )
    reduce_prompt = build_listing_reduce_prompt(
        section_pairs,
        target_entity=target or "",
        total_discovered=total_discovered,
        shown_count=len(briefs),
    )

    diagnostics = {
        "listing_map_reduce": True,
        "documents_total_discovered": total_discovered,
        "documents_in_answer": [b.document_id for b in briefs],
        "documents_missing_from_context": [],
        "documents_mapped": len(briefs),
        "map_max_docs": max_map,
    }
    yield progress.progress("reduce", "start")
    yield progress.progress("reduce", "done")
    return {
        "reduce_prompt": reduce_prompt,
        "citation_map": citation_map,
        "briefs": briefs,
        "diagnostics": diagnostics,
    }


async def stream_listing_reduce_answer(
    reduce_prompt: str,
    query: str,
) -> AsyncIterator[str]:
    messages = [
        {"role": "system", "content": reduce_prompt},
        {"role": "user", "content": query},
    ]
    async for delta in stream_completion(messages=messages, role=ModelRole.LLM):
        yield delta
