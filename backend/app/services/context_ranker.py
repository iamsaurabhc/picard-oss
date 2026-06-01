from __future__ import annotations

import json
import logging
import re
from typing import Literal

from app.config import settings
from app.schemas import SearchHit
from app.services.excerpt_selector import has_identity_signal, identity_signal_strength
from app.services.fts_search import _chunk_is_informative
from app.services.model_router import ModelRole, completion
from app.services.query_understanding import QueryUnderstanding, SearchPass, SubQuestion

logger = logging.getLogger(__name__)

RankMode = Literal["precision", "coverage", "listing"]

RANKER_PROMPT = """Rank document chunks by relevance to the user's legal question.
Return JSON only:
{{"ranked_chunk_ids": ["id1", "id2", ...], "dropped": [{{"chunk_id": "...", "reason": "..."}}], "sub_question_coverage": {{"label": "chunk_id"}}}}

Intent: {intent}
Question: {question}
Sub-questions:
{sub_questions}

Chunks (id | page | preview):
{chunk_list}

Rules:
- Order ranked_chunk_ids from most to least relevant.
- When sub-questions are listed, ensure ranked set can answer each one when evidence exists in the pool.
- Populate sub_question_coverage mapping each sub-question label to the best chunk_id.
- Drop header-only or off-topic chunks (e.g. party name alone with no substance).
- Keep at least one chunk if any candidate is substantive.
- Include every substantive chunk that answers the question before less relevant ones."""

COVERAGE_RANKER_PROMPT = """Select chunks for a broad legal overview answer requiring diverse coverage.
Return JSON only:
{{"ranked_chunk_ids": ["id1", "id2", ...], "dropped": [{{"chunk_id": "...", "reason": "..."}}], "sub_question_coverage": {{}}}}

Coverage goal: {coverage_goal}
Question: {question}
Sub-questions:
{sub_questions}

Chunks (id | page | preview):
{chunk_list}

Rules:
- Maximize DISTINCT information dimensions (parties/roles, central events, amounts/relief, forum, disposition).
- Avoid redundant procedural or judgment paragraphs that repeat the same facts.
- Keep intro/caption chunks (early pages) AND substantive fact/damages chunks AND holding/analysis chunks.
- Drop header-only fragments; keep substantive paragraphs.
- Order by coverage breadth first, then relevance. Include up to {top_k} chunks."""


def _chunk_preview(hit: SearchHit, max_chars: int = 300) -> str:
    text = (hit.text_content or "").strip().replace("\n", " ")
    return text[:max_chars]


def _token_set(text: str, max_chars: int = 200) -> set[str]:
    return set(re.findall(r"\w+", (text or "")[:max_chars].casefold()))


def _jaccard(a: str, b: str) -> float:
    sa, sb = _token_set(a), _token_set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _early_page_threshold(hits: list[SearchHit]) -> int:
    """First quartile page number across the pool."""
    pages = sorted({h.page_number for h in hits if h.page_number > 0})
    if not pages:
        return 1
    idx = max(0, len(pages) // 4 - 1)
    return pages[idx]


def _pass_labels_with_hits(
    pool: list[SearchHit],
    passes: list[SearchPass],
) -> dict[str, list[SearchHit]]:
    """Map each search pass label to pool hits whose text matches pass terms."""
    result: dict[str, list[SearchHit]] = {}
    for p in passes:
        terms = [t.casefold() for t in p.fts_terms if t]
        if not terms:
            continue
        matched = [
            h for h in pool
            if any(t in (h.text_content or "").casefold() for t in terms)
        ]
        if matched:
            result[p.label] = matched
    return result


def _fallback_rank(hits: list[SearchHit], *, top_k: int) -> tuple[list[SearchHit], dict]:
    informative = [h for h in hits if _chunk_is_informative(h.text_content)]
    pool = informative if informative else hits
    ranked = pool[:top_k]
    dropped = len(hits) - len(ranked)
    return ranked, {
        "ranked_count": len(ranked),
        "dropped_count": dropped,
        "used_llm": False,
        "fallback": "bm25_informative",
    }


def _coverage_guardrails(
    ranked: list[SearchHit],
    pool: list[SearchHit],
    *,
    top_k: int,
    search_passes: list[SearchPass] | None = None,
    sub_questions: list[SubQuestion] | None = None,
) -> list[SearchHit]:
    """Structural diversity guardrails replacing keyword facet buckets."""
    max_per_page = 2
    per_page: dict[tuple[str, int], int] = {}
    selected: list[SearchHit] = []
    seen: set[str] = set()

    def _can_add(h: SearchHit) -> bool:
        key = (h.document_id, h.page_number)
        return per_page.get(key, 0) < max_per_page

    def _add(h: SearchHit, *, front: bool = False) -> None:
        if h.chunk_id in seen or not _can_add(h):
            return
        if front:
            selected.insert(0, h)
        else:
            selected.append(h)
        seen.add(h.chunk_id)
        key = (h.document_id, h.page_number)
        per_page[key] = per_page.get(key, 0) + 1

    # Start with LLM-ranked order
    for h in ranked:
        _add(h)

    # Boost identity/name-bearing chunks when a name sub-question is present
    name_requested = any(
        "name" in sq.label.casefold() or "identity" in sq.label.casefold()
        for sq in (sub_questions or [])
    )
    if name_requested:
        identity_hits = [h for h in pool if has_identity_signal(h.text_content)]
        identity_hits.sort(
            key=lambda x: (-identity_signal_strength(x.text_content), -x.score),
        )
        for h in identity_hits:
            if h.chunk_id not in seen:
                _add(h, front=True)
                break

    # Pass coverage: at least one chunk per search pass that had hits
    pass_hits = _pass_labels_with_hits(pool, search_passes or [])
    for label, hits in pass_hits.items():
        if len(selected) >= top_k:
            break
        if any(
            any(t in (h.text_content or "").casefold() for t in (p.fts_terms or []))
            for h in selected
            for p in (search_passes or [])
            if p.label == label
        ):
            continue
        for h in sorted(hits, key=lambda x: x.score):
            if h.chunk_id not in seen:
                _add(h)
                break

    # Early narrative: at least one chunk from first quartile of pages
    early_threshold = _early_page_threshold(pool)
    has_early = any(h.page_number <= early_threshold for h in selected)
    if not has_early:
        early = [
            h for h in pool
            if h.page_number <= early_threshold and _chunk_is_informative(h.text_content)
        ]
        for h in sorted(early, key=lambda x: x.score):
            if h.chunk_id not in seen:
                _add(h, front=True)
                break

    # Page spread: prefer adding from distinct pages when room remains
    covered_pages = {(h.document_id, h.page_number) for h in selected}
    for h in sorted(pool, key=lambda x: x.score):
        if len(selected) >= top_k:
            break
        if h.chunk_id in seen:
            continue
        key = (h.document_id, h.page_number)
        if key not in covered_pages and _can_add(h):
            _add(h)
            covered_pages.add(key)

    # Fill remaining slots by BM25 order
    for h in sorted(pool, key=lambda x: x.score):
        if len(selected) >= top_k:
            break
        _add(h)

    # Redundancy drop: remove chunks with >70% Jaccard overlap on first 200 chars
    deduped: list[SearchHit] = []
    for h in selected:
        if any(_jaccard(h.text_content or "", kept.text_content or "") > 0.7 for kept in deduped):
            continue
        deduped.append(h)

    return deduped[:top_k]


def _listing_document_guardrails(
    ranked: list[SearchHit],
    pool: list[SearchHit],
    *,
    top_k: int,
    min_distinct_documents: int | None = None,
) -> list[SearchHit]:
    """Ensure at least one chunk per discovered document before filling by BM25."""
    max_per_doc = settings.chat_listing_chunks_per_doc
    per_doc: dict[str, int] = {}
    selected: list[SearchHit] = []
    seen: set[str] = set()

    def _can_add(h: SearchHit) -> bool:
        return per_doc.get(h.document_id, 0) < max_per_doc

    def _add(h: SearchHit) -> None:
        if h.chunk_id in seen or not _can_add(h):
            return
        selected.append(h)
        seen.add(h.chunk_id)
        per_doc[h.document_id] = per_doc.get(h.document_id, 0) + 1

    doc_ids = sorted({h.document_id for h in pool})
    min_docs = min_distinct_documents if min_distinct_documents is not None else len(doc_ids)

    for h in ranked:
        _add(h)

    by_doc: dict[str, list[SearchHit]] = {}
    for h in pool:
        by_doc.setdefault(h.document_id, []).append(h)

    for doc_id in doc_ids:
        if sum(1 for h in selected if h.document_id == doc_id) >= 1:
            continue
        for h in sorted(by_doc.get(doc_id, []), key=lambda x: x.score):
            if h.chunk_id not in seen:
                _add(h)
                break

    while len(selected) < top_k:
        added = False
        for doc_id in doc_ids:
            if len(selected) >= top_k:
                break
            for h in sorted(by_doc.get(doc_id, []), key=lambda x: x.score):
                if h.chunk_id not in seen and _can_add(h):
                    _add(h)
                    added = True
                    break
        if not added:
            break

    for h in sorted(pool, key=lambda x: x.score):
        if len(selected) >= top_k:
            break
        _add(h)

    return selected[:top_k]


def _format_sub_questions(understanding: QueryUnderstanding) -> str:
    if not understanding.sub_questions:
        return "(none)"
    return "\n".join(
        f"- {sq.label}: {sq.question}" for sq in understanding.sub_questions
    )


def rank_context(
    question: str,
    understanding: QueryUnderstanding,
    hits: list[SearchHit],
    *,
    top_k: int = 12,
    rank_mode: RankMode = "precision",
    eval_keep_pages: set[tuple[str, int]] | None = None,
) -> tuple[list[SearchHit], dict]:
    """Rank and filter retrieval candidates before citation mapping."""
    if not hits:
        return [], {"ranked_count": 0, "dropped_count": 0, "used_llm": False}

    if not settings.enable_context_ranker:
        ranked, diag = _fallback_rank(hits, top_k=top_k)
        if rank_mode == "listing" or understanding.intent == "entity_matter_listing":
            ranked = _listing_document_guardrails(ranked, hits, top_k=top_k)
            diag["rank_mode"] = "listing"
            diag["distinct_documents"] = len({h.document_id for h in ranked})
            diag["ranked_count"] = len(ranked)
        elif rank_mode == "coverage" or (
            rank_mode == "precision"
            and understanding.intent == "factual_lookup"
            and (len(understanding.search_passes) > 1 or len(understanding.sub_questions) > 1)
        ):
            ranked = _coverage_guardrails(
                ranked, hits, top_k=top_k, search_passes=understanding.search_passes,
                sub_questions=understanding.sub_questions,
            )
            diag["rank_mode"] = rank_mode
            diag["ranked_count"] = len(ranked)
        return ranked, diag

    by_id = {h.chunk_id: h for h in hits}
    chunk_lines = []
    for h in hits[:40]:
        chunk_lines.append(f"- {h.chunk_id} | p{h.page_number} | {_chunk_preview(h)}")

    if rank_mode == "listing":
        prompt_template = COVERAGE_RANKER_PROMPT
    elif rank_mode == "coverage":
        prompt_template = COVERAGE_RANKER_PROMPT
    else:
        prompt_template = RANKER_PROMPT
    prompt_kwargs = {
        "intent": understanding.intent,
        "question": question,
        "chunk_list": "\n".join(chunk_lines),
        "sub_questions": _format_sub_questions(understanding),
    }
    if rank_mode in {"coverage", "listing"}:
        prompt_kwargs["top_k"] = top_k
        prompt_kwargs["coverage_goal"] = (
            understanding.coverage_goal or "per-document matter listing"
        )

    raw = completion(
        messages=[{"role": "user", "content": prompt_template.format(**prompt_kwargs)}],
        role=ModelRole.SLM,
        temperature=0.0,
    )
    if not raw:
        ranked, diag = _fallback_rank(hits, top_k=top_k)
        if rank_mode == "listing":
            ranked = _listing_document_guardrails(ranked, hits, top_k=top_k)
            diag["rank_mode"] = "listing"
        elif rank_mode == "coverage":
            ranked = _coverage_guardrails(
                ranked, hits, top_k=top_k, search_passes=understanding.search_passes,
                sub_questions=understanding.sub_questions,
            )
            diag["rank_mode"] = "coverage"
        if rank_mode in {"coverage", "listing"}:
            diag["ranked_count"] = len(ranked)
            diag["distinct_documents"] = len({h.document_id for h in ranked})
        return ranked, diag

    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        data = json.loads(raw[start:end])
        ranked_ids: list[str] = data.get("ranked_chunk_ids", [])
        dropped_raw = data.get("dropped", [])
        sub_question_coverage = data.get("sub_question_coverage") or {}
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("context ranker parse failed: %s", exc)
        ranked, diag = _fallback_rank(hits, top_k=top_k)
        if rank_mode == "listing":
            ranked = _listing_document_guardrails(ranked, hits, top_k=top_k)
            diag["rank_mode"] = "listing"
            diag["distinct_documents"] = len({h.document_id for h in ranked})
        elif rank_mode == "coverage":
            ranked = _coverage_guardrails(
                ranked, hits, top_k=top_k, search_passes=understanding.search_passes,
                sub_questions=understanding.sub_questions,
            )
            diag["rank_mode"] = "coverage"
        if rank_mode in {"coverage", "listing"}:
            diag["ranked_count"] = len(ranked)
        return ranked, diag

    ranked: list[SearchHit] = []
    seen: set[str] = set()
    for cid in ranked_ids:
        if cid in by_id and cid not in seen:
            ranked.append(by_id[cid])
            seen.add(cid)

    if eval_keep_pages:
        for h in hits:
            key = (h.document_id, h.page_number)
            if key in eval_keep_pages and h.chunk_id not in seen:
                ranked.append(h)
                seen.add(h.chunk_id)

    if not ranked:
        ranked, diag = _fallback_rank(hits, top_k=top_k)
        if rank_mode == "listing":
            ranked = _listing_document_guardrails(ranked, hits, top_k=top_k)
            diag["rank_mode"] = "listing"
            diag["distinct_documents"] = len({h.document_id for h in ranked})
        elif rank_mode == "coverage":
            ranked = _coverage_guardrails(
                ranked, hits, top_k=top_k, search_passes=understanding.search_passes,
                sub_questions=understanding.sub_questions,
            )
            diag["rank_mode"] = "coverage"
        if rank_mode in {"coverage", "listing"}:
            diag["ranked_count"] = len(ranked)
        return ranked, diag

    if rank_mode == "listing":
        ranked = _listing_document_guardrails(ranked, hits, top_k=top_k)
    elif rank_mode == "coverage":
        ranked = _coverage_guardrails(
            ranked, hits, top_k=top_k, search_passes=understanding.search_passes,
            sub_questions=understanding.sub_questions,
        )
    elif (
        rank_mode == "precision"
        and understanding.intent == "factual_lookup"
        and (len(understanding.search_passes) > 1 or len(understanding.sub_questions) > 1)
    ):
        ranked = _coverage_guardrails(
            ranked, hits, top_k=top_k, search_passes=understanding.search_passes,
            sub_questions=understanding.sub_questions,
        )
    else:
        ranked = ranked[:top_k]

    distinct_pages = len({(h.document_id, h.page_number) for h in ranked})
    distinct_documents = len({h.document_id for h in ranked})
    pass_labels_covered = list(_pass_labels_with_hits(hits, understanding.search_passes).keys())
    dropped_count = max(0, len(hits) - len({h.chunk_id for h in ranked}))
    diagnostics = {
        "ranked_count": len(ranked),
        "dropped_count": dropped_count,
        "used_llm": True,
        "rank_mode": rank_mode,
        "distinct_pages": distinct_pages,
        "distinct_documents": distinct_documents,
        "pass_labels_covered": pass_labels_covered,
        "sub_question_coverage": sub_question_coverage if settings.enable_context_ranker else {},
        "sub_questions_covered": list((sub_question_coverage or {}).keys()),
        "dropped_sample": dropped_raw[:3] if isinstance(dropped_raw, list) else [],
    }
    return ranked, diagnostics
