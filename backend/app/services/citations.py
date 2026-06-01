from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas import ContextBundleOut, SearchHit
from app.services.excerpt_selector import has_identity_signal, select_excerpts
from app.services.query_understanding import SubQuestion

MARKER_RE = re.compile(r"\[(\d+)\]")


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


def build_citation_map(
    hits: list[SearchHit],
    bundles: list[ContextBundleOut] | None = None,
    *,
    doc_names: dict[str, str] | None = None,
    excerpt_chars: int = 400,
    question: str = "",
    sub_questions: list[SubQuestion] | None = None,
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

    excerpts = select_excerpts(
        unique_hits,
        question=question,
        sub_questions=sub_questions,
        max_chars=excerpt_chars,
    )

    for hit in unique_hits:
        bundle_id = None
        if bundles:
            for b in bundles:
                if hit.chunk_id in b.chunk_ids:
                    bundle_id = b.bundle_id
                    break
        preview = excerpts.get(hit.chunk_id) or _fallback_excerpt(hit.text_content or "", excerpt_chars)
        pinpoint = preview[:200] if len(preview) > 200 else preview
        refs.append(
            CitationRef(
                index=len(refs) + 1,
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                page=hit.page_number,
                bbox=hit.bbox,
                preview=preview,
                bundle_id=bundle_id,
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


def build_system_prompt(
    citation_map: CitationMap,
    *,
    intent: str = "general",
    sub_questions: list[SubQuestion] | None = None,
    target_entity: str | None = None,
) -> str:
    if intent in {"case_overview", "entity_matter_listing"}:
        excerpt_cap = 800
    elif intent == "factual_lookup":
        excerpt_cap = 600
    else:
        excerpt_cap = 400

    entity_label = target_entity or "the named party"

    if intent == "entity_matter_listing":
        lines = [
            "You are a legal document assistant listing matters involving a party across multiple source documents.",
            f"The user asked for all cases/matters involving {entity_label}.",
            "Answer ONLY using the provided source excerpts.",
            "Structure the answer as follows:",
            "## Summary",
            f"One sentence: how many source documents mention {entity_label} and what kinds of proceedings they appear to be.",
            "",
            "Then one markdown section per source document:",
            "## [Document filename exactly as shown in Sources]",
            "- **Role of party:** defendant/respondent/informant target — only if stated in that document's excerpts [N]",
            "- **Forum / statute:** court, commission, act sections — only from that document [N]",
            "- **Key facts:** central allegations or findings in that document [N]",
            "- **Outcome / stage:** disposition, order, investigation stage — only if stated [N]",
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
    elif intent == "case_overview":
        lines = [
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
            "- In Key facts, describe the central events and underlying incident BEFORE procedural history.",
            "- State amounts, dates, and party names ONLY when present in cited excerpts — never invent.",
            "- Do NOT write 'various legal precedents' without naming them from a cited source.",
            "- If a section lacks evidence, write: 'Sources do not specify [topic].'",
            "- Do not invent citation numbers.",
            "",
            "Sources:",
        ]
    elif intent == "factual_lookup":
        sub_lines = [
            f"- {sq.label.replace('_', ' ').title()}: {sq.question}"
            for sq in (sub_questions or [])
        ]
        lines = [
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
        lines.extend(["", "Sources:"])
    else:
        lines = [
            "You are a legal document assistant. Answer ONLY using the provided source excerpts.",
            "Every factual sentence MUST include an inline citation [N] matching the source list.",
            "When the user asks multiple sub-questions, answer each sub-part separately (use bullets or short paragraphs).",
            "When sources contain relevant evidence, answer substantively — do not claim sources lack all information.",
            "If sources support some sub-questions but not others, answer what you can and write "
            "'Sources do not specify [topic]' for each unsupported sub-part.",
            "Do not invent citation numbers.",
            "",
            "Sources:",
        ]
    for ref in citation_map.refs:
        doc_label = ref.document_name or ref.document_id
        heading_tail = ""
        if ref.heading_path:
            parts = [p.strip() for p in ref.heading_path.split(">") if p.strip()]
            if parts:
                heading_tail = f" — {parts[-1]}"
        body = ref.preview[:excerpt_cap] if ref.preview else ""
        if intent in {"case_overview", "entity_matter_listing", "factual_lookup"}:
            lines.append(
                f"[{ref.index}] {doc_label} (page {ref.page}){heading_tail}\n"
                f"   Excerpt: \"{body}\""
            )
        else:
            pinpoint = ref.pinpoint_quote or ref.preview[:200]
            lines.append(
                f"[{ref.index}] {doc_label} (page {ref.page}){heading_tail}\n"
                f"   Pinpoint: \"{pinpoint}\""
            )
    return "\n".join(lines)


def validate_response(
    answer: str,
    citation_map: CitationMap,
    *,
    mode: str = "SIMPLE",
    allow_partial_disclosure: bool = False,
) -> tuple[str, CitationValidation]:
    valid_indices = {r.index for r in citation_map.refs}
    stripped = 0
    reassigned = 0
    cross_bundle = False

    def _replace_invalid(match: re.Match) -> str:
        nonlocal stripped
        idx = int(match.group(1))
        if idx in valid_indices:
            return match.group(0)
        stripped += 1
        return ""

    cleaned = MARKER_RE.sub(_replace_invalid, answer)

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


def references_for_api(citation_map: CitationMap) -> list[dict]:
    return [
        {
            "index": r.index,
            "chunk_id": r.chunk_id,
            "document_id": r.document_id,
            "document_name": r.document_name,
            "page": r.page,
            "bbox": r.bbox,
            "preview": r.preview,
            "pinpoint_quote": r.pinpoint_quote,
            "heading_path": r.heading_path,
            "bundle_id": r.bundle_id,
        }
        for r in citation_map.refs
    ]
