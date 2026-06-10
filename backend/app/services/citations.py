from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import settings
from app.prompts.legal_rag import contrastive_block, preamble_for_variant
from app.schemas import ContextBundleOut, SearchHit
from app.services.excerpt_selector import (
    has_identity_signal,
    is_table_row_hit,
    overview_facet_excerpt,
    overview_row_excerpt,
    select_excerpts,
    table_row_excerpt,
)
from app.services.query_understanding import SubQuestion

MARKER_RE = re.compile(r"\[(\d+)\]")
_AMOUNT_CLAIM_RE = re.compile(
    r"(?:£|\$|€)\s*[\d,]+(?:\.\d+)?|\b\d{1,3}(?:,\d{3})+\s*(?:pounds?|gbp|usd)\b",
    re.IGNORECASE,
)
_DATE_CLAIM_RE = re.compile(
    r"\b(?:\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|"
    r"January|February|March|April|May|June|July|August|September|October|November|December"
    r"\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_CASE_V_IN_TEXT_RE = re.compile(
    r"\b((?:[A-Z][\w']+)(?:\s+(?:[A-Z][\w']+|of|the)){0,3})\s+v\.?\s+"
    r"([A-Z][\w']+(?:\s+(?:Corporation|Corp|Council|Brothers|Bros|Municipality|Co)[\w']*)*)",
)
_WORD_RE = re.compile(r"[A-Za-z']+")
_BEFORE_V_STOPWORDS = frozenset(
    {
        "the", "that", "this", "than", "case", "court", "stronger", "including", "cited",
        "see", "noted", "where", "when", "if", "as", "and", "or", "but", "for", "with",
        "from", "into", "such", "other", "cases", "also", "held", "said", "held",
    }
)


@dataclass
class CitationRef:
    index: int
    chunk_id: str
    document_id: str
    page: int
    bbox: dict | None
    preview: str
    bundle_id: str | None = None
    document_name: str | None = None
    heading_path: str | None = None
    pinpoint_quote: str | None = None
    highlight_bboxes: list[dict] | None = None
    sentence_anchors: list[dict] | None = None
    page_chunks: list[dict] | None = None


@dataclass
class CitationMap:
    refs: list[CitationRef]
    chunk_id_to_index: dict[str, int]
    bundle_chunk_ids: dict[str, set[str]]


@dataclass
class CitationValidation:
    markers_valid: bool
    facts_stripped: int
    markers_reassigned: int
    cross_bundle_violation: bool


def _fallback_excerpt(text: str, max_len: int) -> str:
    cleaned = (text or "").strip().replace("\n", " ")
    if not cleaned:
        return ""
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len].rstrip() + "…"


def _use_focus_for_intent(intent: str, *, prefer_listing: bool, page_level: bool) -> bool:
    if page_level or (prefer_listing and settings.listing_disable_focus_excerpts):
        return False
    return settings.enable_focus_excerpts


def format_sources_for_prompt(
    citation_map: CitationMap,
    *,
    intent: str = "general",
    excerpt_cap: int = 1200,
    group_by_document: bool = False,
    doc_names: dict[str, str] | None = None,
) -> str:
    """Format citation refs as a Sources block (optional per-document grouping)."""
    lines: list[str] = []
    if group_by_document:
        by_doc: dict[str, list[CitationRef]] = {}
        for ref in citation_map.refs:
            by_doc.setdefault(ref.document_id, []).append(ref)
        for doc_id, refs in by_doc.items():
            label = (doc_names or {}).get(doc_id) or doc_id
            lines.append(f"### Sources for: {label}")
            for ref in refs:
                lines.append(_format_source_block(ref, intent=intent, excerpt_cap=excerpt_cap))
            lines.append("")
    else:
        for ref in citation_map.refs:
            lines.append(_format_source_block(ref, intent=intent, excerpt_cap=excerpt_cap))
    return "\n".join(lines).strip()


def build_citation_map(
    hits: list[SearchHit],
    bundles: list[ContextBundleOut] | None = None,
    *,
    doc_names: dict[str, str] | None = None,
    excerpt_chars: int = 400,
    question: str = "",
    sub_questions: list[SubQuestion] | None = None,
    prefer_amounts: bool = False,
    prefer_listing: bool = False,
    page_level: bool = False,
    intent: str = "general",
    coverage_goal: str = "",
    retrieval_unit: str | None = None,
    db=None,
    workspace_id: str | None = None,
) -> CitationMap:
    seen: set[str] = set()
    refs: list[CitationRef] = []
    bundle_chunk_ids: dict[str, set[str]] = {}
    doc_names = doc_names or {}

    if bundles:
        for bundle in bundles:
            bundle_chunk_ids[bundle.bundle_id] = set(bundle.chunk_ids)

    unique_hits: list[SearchHit] = []
    for hit in hits:
        if hit.chunk_id in seen:
            continue
        seen.add(hit.chunk_id)
        unique_hits.append(hit)

    use_focus = _use_focus_for_intent(intent, prefer_listing=prefer_listing, page_level=page_level)
    skip_slm_excerpts = page_level and (
        prefer_listing
        or (intent == "entity_matter_listing" and settings.listing_disable_focus_excerpts)
    )
    table_primary = retrieval_unit == "table_row" or any(
        is_table_row_hit(h) for h in unique_hits
    )
    if page_level:
        overview_focus = intent == "case_overview" and not table_primary
        excerpts: dict[str, str] = {}
        if table_primary:
            excerpts = overview_row_excerpt(
                unique_hits,
                excerpt_chars,
                question=question,
                sub_questions=sub_questions,
            )
        slm_hits: list[SearchHit] = []
        for h in unique_hits:
            if h.chunk_id in excerpts:
                continue
            text = h.text_content or ""
            prefer_amounts_here = prefer_amounts or overview_focus
            if is_table_row_hit(h):
                excerpts[h.chunk_id] = table_row_excerpt(h, excerpt_chars)
                continue
            focused = (
                overview_facet_excerpt(
                    text,
                    excerpt_chars,
                    question=question,
                    sub_questions=sub_questions,
                )
                if overview_focus
                else None
            )
            if focused:
                excerpts[h.chunk_id] = focused
            elif skip_slm_excerpts or not settings.enable_excerpt_selector:
                excerpts[h.chunk_id] = _fallback_excerpt(text, excerpt_chars)
            else:
                slm_hits.append(h)
        if slm_hits:
            batched = select_excerpts(
                slm_hits,
                question=question,
                sub_questions=sub_questions,
                max_chars=excerpt_chars,
                prefer_amounts=prefer_amounts or overview_focus,
                prefer_listing=prefer_listing,
                intent=intent,
                coverage_goal=coverage_goal,
                db=db,
                workspace_id=workspace_id,
            )
            for h in slm_hits:
                excerpts[h.chunk_id] = batched.get(h.chunk_id) or _fallback_excerpt(
                    h.text_content or "", excerpt_chars,
                )
    elif table_primary:
        excerpts = overview_row_excerpt(
            unique_hits,
            excerpt_chars,
            question=question,
            sub_questions=sub_questions,
        )
    else:
        excerpts = select_excerpts(
            unique_hits,
            question=question,
            sub_questions=sub_questions,
            max_chars=excerpt_chars,
            prefer_amounts=prefer_amounts,
            prefer_listing=prefer_listing,
            intent=intent,
            coverage_goal=coverage_goal,
            db=db,
            workspace_id=workspace_id,
        )

    def _bundle_for_chunk(chunk_id: str, default: str | None = None) -> str | None:
        if not bundles:
            return default
        for bundle in bundles:
            if chunk_id in bundle.chunk_ids:
                return bundle.bundle_id
        return default

    def _append_ref(
        *,
        chunk_id: str,
        document_id: str,
        page: int,
        bbox: dict | None,
        preview: str,
        heading_path: str | None,
        bundle_id: str | None,
        highlight_bboxes: list[dict] | None = None,
        sentence_anchors: list[dict] | None = None,
        page_chunks: list[dict] | None = None,
    ) -> None:
        pinpoint = preview[:200] if len(preview) > 200 else preview
        refs.append(
            CitationRef(
                index=len(refs) + 1,
                chunk_id=chunk_id,
                document_id=document_id,
                page=page,
                bbox=bbox,
                preview=preview,
                bundle_id=bundle_id,
                document_name=doc_names.get(document_id),
                heading_path=heading_path,
                pinpoint_quote=pinpoint,
                highlight_bboxes=highlight_bboxes,
                sentence_anchors=sentence_anchors,
                page_chunks=page_chunks,
            )
        )

    if page_level and db is not None and not table_primary:
        from app.schemas import SearchHit
        from app.services.entity_page_context import (
            _best_chunk_for_sentence,
            anchor_chunk_for_excerpt,
            chunks_for_page_citation_refs,
            page_chunks_payload,
            substantive_chunks_for_page,
        )
        from app.services.fts_search import parse_bbox

        seen_ref_chunks: set[str] = set()
        page_keys = sorted({(h.document_id, h.page_number) for h in unique_hits})
        for document_id, page_number in page_keys:
            page_hits = [
                h
                for h in unique_hits
                if h.document_id == document_id and h.page_number == page_number
            ]
            context_chunk_ids = {h.chunk_id for h in page_hits}
            merged_hit_text = max((h.text_content or "" for h in page_hits), key=len, default="")
            primary_hit = max(page_hits, key=lambda h: len(h.text_content or ""))
            facet_excerpt = (
                excerpts.get(primary_hit.chunk_id)
                or _fallback_excerpt(merged_hit_text, excerpt_chars)
            )
            chunks = chunks_for_page_citation_refs(
                db,
                document_id,
                page_number,
                context_chunk_ids,
                facet_excerpt=facet_excerpt,
            )
            default_bundle = _bundle_for_chunk(page_hits[0].chunk_id)
            page_chunk_meta = page_chunks_payload(db, document_id, page_number)
            from app.services.excerpt_selector import split_sentences

            page_substantive = substantive_chunks_for_page(db, document_id, page_number)
            page_level_anchors: list[dict] = []
            for sent in split_sentences(facet_excerpt) if facet_excerpt else []:
                s = sent.strip()
                if len(s) < 12:
                    continue
                matched, score = _best_chunk_for_sentence(s, page_substantive)
                if matched is None or score <= 0:
                    continue
                page_level_anchors.append(
                    {
                        "sentence": s[:300],
                        "chunk_id": matched.chunk_id,
                        "bbox": parse_bbox(matched.bbox_json),
                        "score": round(score, 3),
                    }
                )
            for chunk in chunks:
                if chunk.chunk_id in seen_ref_chunks:
                    continue
                seen_ref_chunks.add(chunk.chunk_id)
                text = chunk.text_content or ""
                if overview_focus:
                    preview = (
                        overview_facet_excerpt(
                            text,
                            excerpt_chars,
                            question=question,
                            sub_questions=sub_questions,
                        )
                        or _fallback_excerpt(text, excerpt_chars)
                    )
                else:
                    preview = _fallback_excerpt(text, excerpt_chars)
                chunk_hit = SearchHit(
                    chunk_id=chunk.chunk_id,
                    document_id=document_id,
                    page_number=page_number,
                    text_content=text,
                    heading_path=chunk.heading_path,
                    bbox=parse_bbox(chunk.bbox_json),
                    score=0.0,
                )
                anchor_id, anchor_bbox, highlight_bboxes, sentence_anchors = anchor_chunk_for_excerpt(
                    db, chunk_hit, preview,
                )
                merged_anchors = list(page_level_anchors)
                seen_anchor = {a["sentence"].casefold() for a in merged_anchors}
                for a in sentence_anchors or []:
                    key = (a.get("sentence") or "").casefold()
                    if key and key not in seen_anchor:
                        merged_anchors.append(a)
                        seen_anchor.add(key)
                _append_ref(
                    chunk_id=anchor_id,
                    document_id=document_id,
                    page=page_number,
                    bbox=anchor_bbox,
                    preview=preview,
                    heading_path=chunk.heading_path,
                    bundle_id=_bundle_for_chunk(chunk.chunk_id, default_bundle),
                    highlight_bboxes=highlight_bboxes or None,
                    sentence_anchors=merged_anchors or None,
                    page_chunks=page_chunk_meta or None,
                )
    else:
        for hit in unique_hits:
            preview = excerpts.get(hit.chunk_id) or _fallback_excerpt(hit.text_content or "", excerpt_chars)
            if use_focus and preview:
                parts = _SENTENCE_SPLIT_RE.split(preview.strip())
                pinpoint = (parts[0] if parts else preview)[:200]
            else:
                pinpoint = preview[:200] if len(preview) > 200 else preview
            refs.append(
                CitationRef(
                    index=len(refs) + 1,
                    chunk_id=hit.chunk_id,
                    document_id=hit.document_id,
                    page=hit.page_number,
                    bbox=hit.bbox,
                    preview=preview,
                    bundle_id=_bundle_for_chunk(hit.chunk_id),
                    document_name=doc_names.get(hit.document_id),
                    heading_path=hit.heading_path,
                    pinpoint_quote=pinpoint,
                )
            )

    chunk_id_to_index = {r.chunk_id: r.index for r in refs}
    return CitationMap(refs=refs, chunk_id_to_index=chunk_id_to_index, bundle_chunk_ids=bundle_chunk_ids)


def refuse_gate(hits: list[SearchHit], *, search_refused: bool = False) -> bool:
    """Refuse only when no evidence chunks reached the context window."""
    return len(hits) == 0


TABULAR_CELL_CITE_HINT = (
    "When referencing a specific tabular cell, you may use [[cell:column_key:document_id]]."
)


def _format_source_block(
    ref: CitationRef,
    *,
    intent: str,
    excerpt_cap: int,
) -> str:
    doc_label = ref.document_name or ref.document_id
    heading_tail = ""
    if ref.heading_path:
        parts = [p.strip() for p in ref.heading_path.split(">") if p.strip()]
        if parts:
            heading_tail = f" — {parts[-1]}"
    body = ref.preview[:excerpt_cap] if ref.preview else ""
    if intent in {"case_overview", "entity_matter_listing", "factual_lookup"}:
        return (
            f"[{ref.index}] {doc_label} (page {ref.page}){heading_tail}\n"
            f"   Excerpt: \"{body}\""
        )
    pinpoint = ref.pinpoint_quote or ref.preview[:200]
    return (
        f"[{ref.index}] {doc_label} (page {ref.page}){heading_tail}\n"
        f"   Pinpoint: \"{pinpoint}\""
    )


def build_system_prompt(
    citation_map: CitationMap,
    *,
    intent: str = "general",
    sub_questions: list[SubQuestion] | None = None,
    target_entity: str | None = None,
    sub_question_coverage: dict[str, str | None] | None = None,
    coverage_goal: str = "",
    synthesis_mode: str = "chat",
    agent_profile: str = "firm",
    excerpt_cap: int | None = None,
    synthesis_outline: list[str] | None = None,
    profile_canonical_kind: str = "",
    profile_anti_patterns: list[str] | None = None,
) -> str:
    if excerpt_cap is not None:
        cap = excerpt_cap
    elif intent in {"case_overview", "entity_matter_listing"}:
        cap = 1200 if intent == "entity_matter_listing" else 1500
    elif intent == "factual_lookup":
        cap = 600
    else:
        cap = 400
    excerpt_cap = cap

    entity_label = target_entity or "the named party"
    preamble = preamble_for_variant(settings.prompt_variant)
    agent_deep = synthesis_mode == "agent"
    court = agent_profile == "court"
    contrastive = (
        contrastive_block("agent_entity_matter_listing")
        if agent_deep and intent == "entity_matter_listing"
        else contrastive_block(intent)
    )

    if intent == "entity_matter_listing" and agent_deep:
        lines = [
            preamble,
            "",
            contrastive,
            "",
            "You are a legal document assistant producing a multi-matter catalog for Agent mode.",
            (
                "Use neutral, procedural language only; do not predict outcomes or assess credibility."
                if court
                else "Include commercial and procedural detail when present in excerpts."
            ),
            f"The user asked for all cases/matters involving {entity_label}.",
            "Answer ONLY using the provided source excerpts.",
            "Structure:",
            "## Summary",
            f"One or two sentences: how many source documents mention {entity_label}, "
            "forums involved, and date range if stated in excerpts.",
            "",
            "Then one markdown section per source document:",
            "## [Document filename exactly as shown in Sources]",
            "Write substantive prose paragraphs where helpful, plus bullets for:",
            "- **Parties & role:** who is plaintiff/informant/respondent and role of the target party [N]",
            "- **Forum / case no. / statute:** court, commission, case number, act sections — only from that document [N]",
            "- **Key facts & allegations:** core claims, conduct, statutory provisions [N]",
            "- **Dates & outcome / stage:** filing dates, orders, disposition, penalty — only if stated [N]",
            "",
            "Rules:",
            "- Every factual claim MUST include inline [N] from that document's excerpts only.",
            "- Do NOT use case_overview skeleton sections (Parties / Court & citation as top-level only).",
            "- Do NOT write 'Sources do not specify [topic]' for a section when any excerpt in that "
            "document mentions that topic (dates, forum, case number, allegations, outcome).",
            "- Do NOT merge facts from different documents into one narrative.",
            "- Use the document filename from Sources as each section heading.",
            "- Omit sections for documents with no excerpts in Sources.",
            "- Do not invent citation numbers.",
            "",
            "Sources:",
        ]
    elif intent == "entity_matter_listing":
        lines = [
            preamble,
            "",
            contrastive,
            "",
            "You are a legal document assistant listing matters involving a party across multiple source documents.",
            f"The user asked for all cases/matters involving {entity_label}.",
            "Answer ONLY using the provided source excerpts.",
            "Structure the answer as follows:",
            "## Summary",
            f"One sentence: how many source documents mention {entity_label} and what kinds of proceedings they appear to be.",
            "",
            "Then one markdown section per source document:",
            "## [Document filename exactly as shown in Sources]",
            "- **Role of party:** defendant/respondent/opposite party — only if stated in that document's excerpts [N]",
            "- **Other parties / counterparties:** informants, complainants, co-respondents [N]",
            "- **Forum / statute / case id:** court, commission, case number, act sections [N]",
            "- **Procedural posture:** filing stage, investigation, hearing, order type [N]",
            "- **Key facts / allegations:** claims, statutory provisions, findings cited [N]",
            "- **Outcome / reliefs:** disposition, penalty, next step — only if stated [N]",
            "",
            "Rules:",
            "- Every factual bullet MUST include an inline citation [N] from that same document only.",
            "- Do NOT merge facts from different documents into one narrative.",
            "- Use the document filename from the Sources list as each section heading.",
            "- If excerpts for a document are thin, note 'Limited detail in retrieved excerpts' and cite what exists.",
            "- Omit section headings for documents that have no excerpts in Sources.",
            "- State party names, dates, and amounts ONLY when present in cited excerpts.",
            "- Do not invent citation numbers.",
            "",
            "Sources:",
        ]
    elif synthesis_outline:
        section_lines = "\n".join(f"## {s}" for s in synthesis_outline)
        kind_line = (
            f"This document is described as: {profile_canonical_kind}."
            if profile_canonical_kind
            else "Use the document profile and excerpts to structure the answer."
        )
        anti_lines = profile_anti_patterns or []
        lines = [
            preamble,
            "",
            contrastive_block("profile_synthesis"),
            "",
            "You are a legal document assistant. Answer ONLY using the provided source excerpts.",
            kind_line,
            "Structure the answer with these markdown sections (omit a section ONLY if sources are truly silent):",
            section_lines,
            "",
            "Rules:",
            "- Every factual sentence or bullet MUST include an inline citation [N].",
            "- When sources are labeled table rows (Clause: / Preferred positions: / Fallback positions:), "
            "use one bullet per clause/topic and cite the row-specific source [N] for that row.",
            "- Do not reuse the same [N] for multiple unrelated clauses — each distinct row excerpt gets its own citation.",
            "- Quote preferred and fallback positions verbatim from row excerpts when present; do not summarize away detail.",
            "- When excerpts contain relevant evidence, answer substantively — do not claim sources lack all information.",
            "- Do NOT use litigation case skeleton sections (Parties / Court & citation / Damages) unless excerpts support them.",
        ]
        for anti in anti_lines[:4]:
            lines.append(f"- {anti}")
        lines.extend([
            "- Do not invent citation numbers.",
            "",
            "Sources:",
        ])
    elif intent == "case_overview":
        lines = [
            preamble,
            "",
            contrastive,
            "",
            "You are a legal document assistant preparing a CASE OVERVIEW for a lawyer.",
            "Answer ONLY using the provided source excerpts.",
            "Structure the answer with these markdown sections (omit a section ONLY if sources are truly silent):",
            "## Parties",
            "## Court & citation",
            "## Nature of claim",
            "## Key facts",
            "## Damages / relief sought",
            "## Dates & procedural history",
            "## Outcome / holdings",
            "",
            "Rules:",
            "- Every factual sentence or bullet MUST include an inline citation [N].",
            "- Distinguish roles clearly: claimant/plaintiff vs injured third party vs defendant/respondent.",
            "- In Parties, name litigating parties AND any injured or deceased person identified in excerpts "
            "(e.g. plaintiff's infant son by name), with their role — not only the formal parties.",
            "- In Key facts, describe the central events and underlying incident (including death or serious "
            "injury when stated) BEFORE procedural history.",
            "- In Court & citation, include the forum or commission (not only 'court'), and case or diary numbers "
            "when stated in excerpts.",
            "- In Damages / relief sought, state every monetary amount, prayed relief, penalty, direction, or "
            "other remedy explicitly mentioned in excerpts (e.g. 'claimed damages in the sum of £1,000'). "
            "Never write 'Sources do not specify' if any excerpt contains damages, relief, penalty, or sum language.",
            "- In Dates & procedural history, include filing dates, relevant periods, and procedural milestones "
            "when present in excerpts.",
            "- In Outcome / holdings, state final orders or judgments when present; if only a procedural stage "
            "is described (e.g. under investigation), state that stage with a citation.",
            "- State amounts, dates, and party names ONLY when present in cited excerpts — never invent.",
            "- Do NOT write 'various legal precedents' without naming them from a cited source.",
            "- Use the **exact case-name spelling from source excerpts** in all factual statements — "
            "never echo the user's query spelling when it differs from sources.",
            "- If the user misspelled a cited case, note that once at the start using the source spelling only; "
            "do not use the incorrect spelling anywhere in the answer body.",
            "- If a section lacks evidence, write: 'Sources do not specify [topic].'",
            "- Do not invent citation numbers.",
            "- For Damages / relief sought and Dates & procedural history, cite the source blocks under those headings.",
            "",
            "Sources:",
        ]
    elif intent == "factual_lookup":
        sub_lines = [
            f"- {sq.label.replace('_', ' ').title()}: {sq.question}"
            for sq in (sub_questions or [])
        ]
        lines = [
            preamble,
            "",
            contrastive,
            "",
            "You are a legal document assistant. Answer ONLY using the provided source excerpts.",
            "Every factual sentence MUST include an inline citation [N] matching the source list.",
            "Format the answer as professional markdown:",
            "## Answer",
            "Then one bullet per sub-question using clear labels (e.g. **Son's name:**, **Age:**, **Date of accident:**).",
            "Write in complete sentences where possible; be concise and precise.",
            "When excerpts name a person (including OCR spacing like 'Ma x Chester'), state that name for name questions.",
            "When sources contain relevant evidence, answer substantively — do not claim sources lack all information.",
            "If sources support some sub-questions but not others, answer what you can and write "
            "'Sources do not specify [topic]' for each unsupported sub-part.",
            "Do not invent citation numbers.",
        ]
        if sub_lines:
            lines.extend(["", "Sub-questions to answer:", *sub_lines])
        if coverage_goal:
            lines.extend(["", f"Coverage goal: {coverage_goal}"])
        lines.extend(["", "Sources:"])
    else:
        lines = [
            preamble,
            "",
            contrastive,
            "",
            "You are a legal document assistant. Answer ONLY using the provided source excerpts.",
            "Every factual sentence MUST include an inline citation [N] matching the source list.",
            "When the user asks multiple sub-questions, answer each sub-part separately (use bullets or short paragraphs).",
            "When sources contain relevant evidence, answer substantively — do not claim sources lack all information.",
            "Use the exact case-name spelling from source excerpts — never echo the user's misspelled query form.",
            "If the user misspelled a cited case, note that once at the start using the source spelling only.",
            "If sources support some sub-questions but not others, answer what you can and write "
            "'Sources do not specify [topic]' for each unsupported sub-part.",
            "Do not invent citation numbers.",
            "",
            "Sources:",
        ]
    chunk_to_ref = {r.chunk_id: r for r in citation_map.refs}
    if intent == "factual_lookup" and sub_questions and sub_question_coverage:
        cited_ids: set[str] = set()
        for sq in sub_questions:
            cid = sub_question_coverage.get(sq.label)
            ref = chunk_to_ref.get(cid) if cid else None
            label = sq.label.replace("_", " ").title()
            lines.append(f"### Evidence for: {label}")
            if ref:
                lines.append(_format_source_block(ref, intent=intent, excerpt_cap=excerpt_cap))
                cited_ids.add(ref.chunk_id)
            else:
                lines.append("(no dedicated excerpt in context for this sub-question)")
        for ref in citation_map.refs:
            if ref.chunk_id not in cited_ids:
                lines.append(_format_source_block(ref, intent=intent, excerpt_cap=excerpt_cap))
    elif intent == "case_overview" and sub_questions and sub_question_coverage:
        cited_ids: set[str] = set()
        facet_order = [sq.label for sq in sub_questions]
        for label in facet_order:
            sq = next((s for s in sub_questions if s.label == label), None)
            if not sq:
                continue
            cid = sub_question_coverage.get(label)
            ref = chunk_to_ref.get(cid) if cid else None
            facet_title = label.replace("_", " ").title()
            lines.append(f"### Evidence for: {facet_title}")
            if ref:
                lines.append(_format_source_block(ref, intent=intent, excerpt_cap=excerpt_cap))
                cited_ids.add(ref.chunk_id)
            else:
                lines.append(f"(no dedicated excerpt in context for {facet_title.lower()})")
        for ref in citation_map.refs:
            if ref.chunk_id not in cited_ids:
                lines.append(_format_source_block(ref, intent=intent, excerpt_cap=excerpt_cap))
    else:
        for ref in citation_map.refs:
            lines.append(_format_source_block(ref, intent=intent, excerpt_cap=excerpt_cap))
    return "\n".join(lines)


def _token_set(text: str) -> set[str]:
    return {t.casefold() for t in re.findall(r"\w+", text or "") if len(t) > 2}


def _overlap_score(claim: str, source: str) -> float:
    a, b = _token_set(claim), _token_set(source)
    if not a:
        return 0.0
    return len(a & b) / len(a)


def _verify_atomic_claims_in_preview(claim: str, preview: str) -> bool:
    preview_cf = preview.casefold()
    for m in _AMOUNT_CLAIM_RE.finditer(claim):
        if m.group(0).casefold() not in preview_cf:
            return False
    for m in _DATE_CLAIM_RE.finditer(claim):
        if m.group(0).casefold() not in preview_cf:
            return False
    return True


def _fact_verify_and_strip(cleaned: str, citation_map: CitationMap) -> tuple[str, int]:
    """Remove sentences whose amounts/dates are not supported by cited preview."""
    refs_by_index = {r.index: r for r in citation_map.refs}
    stripped = 0
    paragraphs = cleaned.split("\n\n")
    out_paras: list[str] = []

    for para in paragraphs:
        sentences = _SENTENCE_SPLIT_RE.split(para.strip()) if para.strip() else []
        kept: list[str] = []
        for sent in sentences:
            if not sent.strip():
                continue
            markers = [int(m.group(1)) for m in MARKER_RE.finditer(sent)]
            has_atomic = bool(_AMOUNT_CLAIM_RE.search(sent) or _DATE_CLAIM_RE.search(sent))
            if not has_atomic or not markers:
                kept.append(sent)
                continue
            supported = any(
                _verify_atomic_claims_in_preview(sent, refs_by_index[idx].preview)
                for idx in markers
                if idx in refs_by_index
            )
            if supported:
                kept.append(sent)
            else:
                stripped += 1
        if kept:
            out_paras.append(" ".join(kept))

    return "\n\n".join(out_paras), stripped


def _normalize_case_party_a(party_a: str) -> str | None:
    words = party_a.split()
    if not words:
        return None
    if len(words) <= 4 and not any(w.casefold() in _BEFORE_V_STOPWORDS for w in words):
        return party_a.strip()
    good = [w for w in words if w[:1].isupper() and w.casefold() not in _BEFORE_V_STOPWORDS]
    if not good:
        return None
    return good[-1]


def _source_case_canonical_tokens(citation_map: CitationMap) -> dict[str, str]:
    """casefold token -> authoritative surface form from source previews."""
    canonical: dict[str, str] = {}
    for ref in citation_map.refs:
        text = ref.preview or ""
        for match in _CASE_V_IN_TEXT_RE.finditer(text):
            party_a = _normalize_case_party_a(match.group(1).strip())
            party_b = match.group(2).strip()
            if not party_a:
                continue
            for word in _WORD_RE.findall(f"{party_a} {party_b}"):
                if len(word) >= 3:
                    key = word.casefold()
                    if key not in canonical or (word[:1].isupper() and not canonical[key][:1].isupper()):
                        canonical[key] = word
        for word in _WORD_RE.findall(text):
            if len(word) >= 4 and word[:1].isupper():
                key = word.casefold()
                if key not in canonical:
                    canonical[key] = word
    return canonical


def _source_case_citations(citation_map: CitationMap) -> list[str]:
    """Full 'Party v Party' strings from source previews, longest first."""
    found: list[str] = []
    seen: set[str] = set()
    for ref in citation_map.refs:
        for match in _CASE_V_IN_TEXT_RE.finditer(ref.preview or ""):
            party_a = _normalize_case_party_a(match.group(1).strip())
            party_b = match.group(2).strip()
            if not party_a:
                continue
            cite = f"{party_a} v {party_b}"
            key = cite.casefold()
            if key not in seen:
                seen.add(key)
                found.append(cite)
    return sorted(found, key=len)


def _same_length_one_edit(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    return sum(x != y for x, y in zip(a, b)) == 1


def _source_replacement_for_query_token(
    query_cf: str,
    source_canonical: dict[str, str],
) -> str | None:
    if query_cf in source_canonical:
        return None
    for i, c in enumerate(query_cf):
        if c == "v":
            alt = query_cf[:i] + "w" + query_cf[i + 1 :]
            if alt in source_canonical:
                return source_canonical[alt]
        elif c == "w":
            alt = query_cf[:i] + "v" + query_cf[i + 1 :]
            if alt in source_canonical:
                return source_canonical[alt]
    for src_cf, display in source_canonical.items():
        if _same_length_one_edit(query_cf, src_cf):
            return display
    return None


def _query_party_surfaces(query: str) -> list[tuple[str, str]]:
    from app.services.query_understanding import _case_name_terms

    terms = _case_name_terms(query) or []
    surfaces: list[tuple[str, str]] = []
    for term in terms:
        m = re.search(rf"\b({re.escape(term)})\b", query, re.IGNORECASE)
        surface = m.group(1) if m else term.title()
        surfaces.append((term.casefold(), surface))
    return surfaces


def _align_case_names_to_sources(
    answer: str,
    citation_map: CitationMap,
    *,
    query: str = "",
) -> tuple[str, int]:
    """Replace query-echo misspellings with spellings proven in source previews."""
    source_canonical = _source_case_canonical_tokens(citation_map)
    if not source_canonical:
        return answer, 0

    replacements = 0
    aligned = answer
    for query_cf, query_surface in _query_party_surfaces(query):
        if query_cf in source_canonical:
            continue
        replacement = _source_replacement_for_query_token(query_cf, source_canonical)
        if not replacement:
            continue
        pattern = re.compile(rf"\b{re.escape(query_surface)}\b", re.IGNORECASE)
        new_text, n = pattern.subn(replacement, aligned)
        if n:
            aligned = new_text
            replacements += n

    source_cites = _source_case_citations(citation_map)
    if query and source_cites:
        q_terms = {t for t, _ in _query_party_surfaces(query)}
        for cite in source_cites:
            cite_tokens = {w.casefold() for w in _WORD_RE.findall(cite) if len(w) >= 3}
            if not q_terms & cite_tokens:
                continue
            user_cite_match = re.search(
                rf"\b({'|'.join(re.escape(s) for _, s in _query_party_surfaces(query))})"
                rf"\s+v\.?\s+([\w']+(?:\s+[\w']+)*)",
                aligned,
                re.IGNORECASE,
            )
            if user_cite_match:
                wrong = user_cite_match.group(0)
                if wrong.casefold() != cite.casefold() and wrong.casefold() not in {
                    c.casefold() for c in source_cites
                }:
                    aligned = aligned.replace(wrong, cite, 1)
                    replacements += 1
            break

    if replacements and query:
        q_terms = {t for t, _ in _query_party_surfaces(query)}
        matching = [
            c for c in source_cites
            if q_terms & {w.casefold() for w in _WORD_RE.findall(c)}
        ]
        primary_cite = min(matching, key=len) if matching else (source_cites[0] if source_cites else None)
        if primary_cite and "Note:" not in aligned[:200]:
            note = (
                f"**Note:** Sources refer to **{primary_cite}** "
                f"(not the spelling used in your query).\n\n"
            )
            aligned = note + aligned

    return aligned, replacements


def _reassign_markers(
    cleaned: str,
    citation_map: CitationMap,
    *,
    intent: str | None = None,
) -> tuple[str, int]:
    """Rewrite each cited sentence to the ref index that best supports its claim."""
    from app.services.citation_binding import (
        OVERLAP_THRESHOLD,
        best_ref_index_for_claim,
        best_ref_index_for_claim_scoped,
    )

    refs = citation_map.refs
    if len(refs) < 2:
        return cleaned, 0

    refs_by_index = {r.index: r for r in refs}
    distinct_doc_ids = {r.document_id for r in refs if r.document_id}
    scope_to_document = (
        intent in {"entity_matter_listing", "case_overview"}
        and len(distinct_doc_ids) > 1
    )

    reassigned = 0

    def _replace_sentence(sentence: str) -> str:
        nonlocal reassigned
        if not MARKER_RE.search(sentence):
            return sentence
        claim = MARKER_RE.sub("", sentence).strip()
        if len(claim) < 12:
            return sentence
        if scope_to_document:
            marker_match = MARKER_RE.search(sentence)
            existing_idx = int(marker_match.group(1)) if marker_match else None
            existing_ref = refs_by_index.get(existing_idx) if existing_idx else None
            restrict_doc = existing_ref.document_id if existing_ref else None
            best_idx, best_score = best_ref_index_for_claim_scoped(
                claim, refs, restrict_document_id=restrict_doc,
            )
        else:
            best_idx, best_score = best_ref_index_for_claim(claim, refs)
        if best_idx is None or best_score < OVERLAP_THRESHOLD:
            return sentence
        new_sentence = MARKER_RE.sub(f"[{best_idx}]", sentence)
        if new_sentence != sentence:
            reassigned += 1
        return new_sentence

    parts = []
    for para in cleaned.split("\n\n"):
        if not para.strip():
            continue
        lines = para.split("\n")
        if any(MARKER_RE.search(line) for line in lines):
            parts.append("\n".join(_replace_sentence(line) if MARKER_RE.search(line) else line for line in lines))
            continue
        sents = _SENTENCE_SPLIT_RE.split(para.strip())
        parts.append(" ".join(_replace_sentence(s) for s in sents if s))
    return "\n\n".join(parts), reassigned


_MARKDOWN_STRUCTURE_INTENTS = frozenset({"entity_matter_listing", "case_overview"})


def validate_response(
    answer: str,
    citation_map: CitationMap,
    *,
    mode: str = "SIMPLE",
    allow_partial_disclosure: bool = False,
    intent: str | None = None,
    query: str = "",
) -> tuple[str, CitationValidation]:
    valid_indices = {r.index for r in citation_map.refs}
    stripped = 0
    reassigned = 0
    cross_bundle = False
    preserve_structure = intent in _MARKDOWN_STRUCTURE_INTENTS

    def _replace_invalid(match: re.Match) -> str:
        nonlocal stripped
        idx = int(match.group(1))
        if idx in valid_indices:
            return match.group(0)
        stripped += 1
        return ""

    cleaned = MARKER_RE.sub(_replace_invalid, answer)
    cleaned, _ = _align_case_names_to_sources(cleaned, citation_map, query=query)
    if preserve_structure:
        if intent in {"case_overview", "entity_matter_listing"}:
            cleaned, reassigned = _reassign_markers(cleaned, citation_map, intent=intent)
    else:
        cleaned, fact_stripped = _fact_verify_and_strip(cleaned, citation_map)
        stripped += fact_stripped
        cleaned, reassigned = _reassign_markers(cleaned, citation_map, intent=intent)

    if mode == "MULTI_CONSTRAINT" and not allow_partial_disclosure and len(citation_map.bundle_chunk_ids) > 1:
        cited_indices = {int(m.group(1)) for m in MARKER_RE.finditer(cleaned)}
        bundle_ids: set[str] = set()
        for idx in cited_indices:
            ref = next((r for r in citation_map.refs if r.index == idx), None)
            if ref and ref.bundle_id:
                bundle_ids.add(ref.bundle_id)
        if len(bundle_ids) > 1:
            cross_bundle = True

    validation = CitationValidation(
        markers_valid=stripped == 0 and not cross_bundle,
        facts_stripped=stripped,
        markers_reassigned=reassigned,
        cross_bundle_violation=cross_bundle,
    )
    if cross_bundle:
        cleaned += (
            "\n\n_Note: Citations span multiple context bundles; verify each bundle separately._"
        )
    return cleaned, validation


def cited_indices_in_answer(answer: str) -> list[int]:
    """Citation marker indices in first-appearance order."""
    seen: set[int] = set()
    ordered: list[int] = []
    for match in MARKER_RE.finditer(answer):
        idx = int(match.group(1))
        if idx not in seen:
            seen.add(idx)
            ordered.append(idx)
    return ordered


def _document_binding_chunks(citation_map: CitationMap) -> dict[str, list[dict]]:
    """All chunk surfaces in the map, grouped by document (for cross-page cite binding)."""
    by_doc: dict[str, dict[str, dict]] = {}
    for ref in citation_map.refs:
        bucket = by_doc.setdefault(ref.document_id, {})
        for anchor in ref.sentence_anchors or []:
            if not isinstance(anchor, dict):
                continue
            cid = anchor.get("chunk_id") or ref.chunk_id
            bucket[cid] = {
                "chunk_id": cid,
                "text": (anchor.get("sentence") or "")[:800],
                "bbox": anchor.get("bbox"),
                "page": ref.page,
            }
        for pc in ref.page_chunks or []:
            if not isinstance(pc, dict):
                continue
            cid = pc.get("chunk_id") or ref.chunk_id
            bucket[cid] = {
                "chunk_id": cid,
                "text": (pc.get("text") or "")[:800],
                "bbox": pc.get("bbox"),
                "page": pc.get("page") or ref.page,
            }
        if ref.preview:
            bucket[ref.chunk_id] = {
                "chunk_id": ref.chunk_id,
                "text": ref.preview[:800],
                "bbox": ref.bbox,
                "page": ref.page,
            }
    return {doc_id: list(chunks.values()) for doc_id, chunks in by_doc.items()}


def references_for_api(
    citation_map: CitationMap,
    *,
    answer: str | None = None,
    cited_only: bool = False,
) -> list[dict]:
    refs = citation_map.refs
    if cited_only and answer:
        cited_order = cited_indices_in_answer(answer)
        by_index = {r.index: r for r in refs}
        refs = [by_index[i] for i in cited_order if i in by_index]
    doc_binding = _document_binding_chunks(citation_map)
    return [
        {
            "index": r.index,
            "chunk_id": r.chunk_id,
            "document_id": r.document_id,
            "document_name": r.document_name,
            "page": r.page,
            "bbox": r.bbox,
            "highlight_bboxes": r.highlight_bboxes,
            "sentence_anchors": r.sentence_anchors,
            "page_chunks": r.page_chunks,
            "document_binding_chunks": [
                c
                for c in doc_binding.get(r.document_id, [])
                if c.get("page") == r.page
            ],
            "preview": r.preview,
            "pinpoint_quote": r.pinpoint_quote,
            "heading_path": r.heading_path,
            "bundle_id": r.bundle_id,
        }
        for r in refs
    ]
