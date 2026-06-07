"""Per-document map-reduce synthesis for entity matter listing."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import settings
from app.prompts.legal_rag import contrastive_block_for_listing_phase, preamble_for_variant
from app.schemas import SearchHit
from app.services.citation_kernel import merge_evidence_maps
from app.services.citations import (
    CitationMap,
    build_citation_map,
    format_sources_for_prompt,
)
from app.services.document_context import build_document_context
from app.services.entity_index import count_documents_for_party
from app.services.entity_page_context import (
    cross_page_reference_hits,
    party_canonicals_from_understanding,
    retrieve_listing_page_hits,
)
from app.services.model_router import ModelRole, completion, stream_completion
from app.services.query_understanding import QueryUnderstanding
from app.services.retrieval_progress import RetrievalProgressEmitter

@dataclass
class ListingDocBrief:
    document_id: str
    file_name: str
    brief_markdown: str
    citation_map: CitationMap


def _canonicals_from_understanding(understanding: QueryUnderstanding) -> list[str]:
    return party_canonicals_from_understanding(understanding)


def retrieve_hits_for_listing_document(
    db: Session,
    *,
    workspace_id: str,
    document_id: str,
    understanding: QueryUnderstanding,
    query: str,
    canonicals: list[str],
    agent_deep: bool = False,
    chunks_per_doc: int | None = None,
) -> tuple[list[SearchHit], dict]:
    """Entity-ranked full-page context for one listing document."""
    del chunks_per_doc
    hits, diag = retrieve_listing_page_hits(
        db,
        workspace_id=workspace_id,
        document_id=document_id,
        understanding=understanding,
        query=query,
        canonicals=canonicals,
        agent_deep=agent_deep,
    )
    extra = cross_page_reference_hits(
        db,
        workspace_id=workspace_id,
        document_id=document_id,
        understanding=understanding,
        query=query,
        seed_hits=hits,
        canonicals=canonicals,
    )
    if extra:
        seen_pages = {h.page_number for h in hits}
        for h in extra:
            if h.page_number not in seen_pages:
                hits.append(h)
                seen_pages.add(h.page_number)
        diag["cross_page_added"] = len(extra)
    return hits, diag


def build_listing_map_prompt(
    citation_map: CitationMap,
    *,
    file_name: str,
    target_entity: str,
    metadata_block: str = "",
    agent_deep: bool = False,
) -> str:
    preamble = preamble_for_variant(settings.prompt_variant)
    contrastive = contrastive_block_for_listing_phase("map", agent_deep=agent_deep)
    excerpt_cap = (
        settings.agent_listing_map_excerpt_chars
        if agent_deep
        else settings.chat_listing_map_excerpt_chars
    )
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
    ]
    if agent_deep:
        lines.extend([
            "- **Case / matter id:** case number, diary number, investigation id — only if stated [N]",
            "- **Dates / chronology:** filing, order, hearing dates — only if stated [N]",
        ])
    lines.extend([
        "- **Forum / statute:** court, commission, act sections [N]",
        "- **Procedural posture:** informant, respondent, stage of proceeding [N]",
        "- **Key facts / allegations:** who filed against whom, provisions, findings — only if stated [N]",
        "- **Outcome / reliefs:** disposition, order, penalty, next step — only if stated [N]",
    ])
    lines.extend([
        "",
        "Rules:",
        "- Every factual bullet MUST include inline [N] from Sources below.",
        "- Use citation numbers only from this document's Sources.",
        "- If excerpts are thin, write one bullet: 'Limited detail in retrieved excerpts' with any cite you have.",
        "- Do not invent citation numbers.",
    ])
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
    agent_deep: bool = False,
    citation_map: CitationMap | None = None,
    doc_names: dict[str, str] | None = None,
) -> str:
    preamble = preamble_for_variant(settings.prompt_variant)
    contrastive = contrastive_block_for_listing_phase("reduce", agent_deep=agent_deep)
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
        "Expand each section into substantive professional detail (multiple bullets or short paragraphs).",
        "Use briefs for structure; add facts only when supported by per-document sources below.",
        "",
        "Rules:",
        "- Do NOT merge facts across documents into one narrative.",
        "- Include every document brief below as its own ## section.",
        "- Keep citation markers [N] exactly as in the briefs and sources.",
        "- Do not invent citation numbers.",
        "",
        "Per-document briefs:",
    ]
    for file_name, brief_md in brief_sections:
        lines.append(f"### Brief for: {file_name}")
        lines.append(brief_md.strip() or "- Limited detail in retrieved excerpts.")
        lines.append("")
    if citation_map and citation_map.refs:
        excerpt_cap = (
            settings.agent_listing_map_excerpt_chars
            if agent_deep
            else settings.chat_listing_map_excerpt_chars
        )
        lines.extend([
            "",
            "Per-document sources (expand briefs using these; cite with existing [N] only):",
            format_sources_for_prompt(
                citation_map,
                intent="entity_matter_listing",
                excerpt_cap=excerpt_cap,
                group_by_document=True,
                doc_names=doc_names,
            ),
        ])
    return "\n".join(lines)


def merge_listing_briefs(
    briefs: list[ListingDocBrief],
) -> tuple[list[tuple[str, str]], CitationMap]:
    """Combine per-doc briefs into global citation map and renumbered section text."""
    steps = [(b.citation_map, b.brief_markdown) for b in briefs]
    combined_map, renumbered = merge_evidence_maps(steps)
    sections = [
        (briefs[i].file_name, renumbered[i] or "")
        for i in range(len(briefs))
    ]
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
    agent_deep: bool = False,
) -> ListingDocBrief:
    hits, _page_diag = retrieve_hits_for_listing_document(
        db,
        workspace_id=workspace_id,
        document_id=document_id,
        understanding=understanding,
        query=query,
        canonicals=canonicals,
        agent_deep=agent_deep,
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

    excerpt_chars = (
        settings.agent_listing_map_excerpt_chars
        if agent_deep
        else settings.chat_listing_map_excerpt_chars
    )
    citation_map = build_citation_map(
        hits,
        None,
        doc_names=doc_names,
        excerpt_chars=excerpt_chars,
        question=query,
        sub_questions=understanding.sub_questions,
        prefer_listing=True,
        page_level=True,
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
        agent_deep=agent_deep,
    )
    from app.services.pii_proxy import batch_register_texts, get_active_proxy

    proxy = get_active_proxy()
    if proxy is not None:
        texts = [query, meta, prompt]
        for ref in citation_map.refs:
            if ref.preview:
                texts.append(ref.preview)
        batch_register_texts(proxy, texts)

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
    document_ids: list[str] | None = None,
) -> bool:
    del tabular_review_id, db
    use = settings.enable_listing_map_reduce if enabled is None else enabled
    effective = list(document_ids_discovered)
    if document_ids:
        scoped = set(document_ids)
        effective = [d for d in document_ids_discovered if d in scoped]
    count = len(effective) if effective else len(document_ids_discovered)
    return use and count >= settings.listing_map_reduce_min_docs


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
    agent_deep: bool = False,
    map_max_docs: int | None = None,
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

    if map_max_docs is not None:
        max_map = map_max_docs
    elif agent_deep:
        max_map = settings.agent_listing_map_max_docs
    else:
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
        yield progress.progress("page_rank", "start", document_id=doc_id, document_name=file_name)
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
            agent_deep=agent_deep,
        )
        briefs.append(brief)
        pages_selected = sorted({r.page for r in brief.citation_map.refs})
        yield progress.progress(
            "page_rank",
            "done",
            document_id=doc_id,
            document_name=file_name,
            pages_selected=pages_selected,
        )
        yield progress.progress(
            "map",
            "done",
            document_id=doc_id,
            document_name=file_name,
            chunk_count=len(brief.citation_map.refs),
            pages_selected=pages_selected,
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
        agent_deep=agent_deep,
        citation_map=citation_map,
        doc_names=doc_names,
    )
    if agent_deep:
        reduce_prompt = (
            "Synthesize a multi-document legal catalog (Agent mode). "
            "Use per-file ## [filename] sections with forum, case numbers, allegations, "
            "and outcomes when present in the briefs. Do not use case_overview skeleton headings.\n\n"
            + reduce_prompt
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
