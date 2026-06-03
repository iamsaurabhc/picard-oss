from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.schemas import SearchRequest
from app.services.context_ranker import rank_context
from app.services.overview_retrieval import overview_retrieve
from app.services.query_understanding import understand_query
from app.services.search import execute_search

_PARAPHRASE_BENCH_IDS = frozenset({"chester_bench_002", "chester_bench_003"})

_MIN_SUBSTANTIVE_CHARS = 40
_OVERVIEW_RECALL_K = 20


def load_gold_labels(path: Path) -> list[dict]:
    if not path.exists():
        return []
    labels = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            labels.append(json.loads(line))
    return labels


def run_gold_label(db: Session, label: dict) -> dict:
    retrieval_mode = label.get("mode", "auto")
    if label.get("mode") == "MULTI_CONSTRAINT":
        retrieval_mode = "multi_constraint"
    elif label.get("mode") == "SIMPLE":
        retrieval_mode = "simple"

    doc_ids = [label["document_id"]] if label.get("document_id") else None
    query_text = label.get("query") or ""
    if label.get("diagnostic_query") and label.get("query_style") == "diagnostic":
        query_text = label["query"]

    understanding = understand_query(
        query_text,
        retrieval_mode=retrieval_mode,
        db=db,
        workspace_id=label["workspace_id"],
        document_ids=doc_ids,
    )

    if understanding.intent == "case_overview":
        pool_hits, overview_diag = overview_retrieve(
            db,
            understanding,
            workspace_id=label["workspace_id"],
            document_ids=doc_ids,
            query=label["query"],
        )
        ranked_hits, rank_diag = rank_context(
            label["query"],
            understanding,
            pool_hits,
            top_k=settings.chat_overview_top_k,
            rank_mode="coverage",
        )
        diagnostics = {**overview_diag, **rank_diag, "intent": "case_overview"}
        return {
            "query_id": label["query_id"],
            "mode": "SIMPLE",
            "refused": len(ranked_hits) == 0,
            "hit_ids": [h.chunk_id for h in ranked_hits],
            "hit_pages": [(h.document_id, h.page_number) for h in ranked_hits],
            "hit_text_lens": [len((h.text_content or "").strip()) for h in ranked_hits],
            "bundles": 0,
            "diagnostics": diagnostics,
        }

    body = SearchRequest(
        query=label["query"],
        workspace_id=label["workspace_id"],
        retrieval_mode=retrieval_mode,
        allow_partial_disclosure=label.get("allow_partial", False),
    )
    response = execute_search(db, body)
    return {
        "query_id": label["query_id"],
        "mode": response.mode,
        "refused": response.refused,
        "hit_ids": [h.chunk_id for h in response.hits],
        "hit_pages": [(h.document_id, h.page_number) for h in response.hits],
        "hit_text_lens": [len((h.text_content or "").strip()) for h in response.hits],
        "bundles": len(response.bundles or []),
        "diagnostics": response.retrieval_diagnostics,
    }


def _page_recall(result: dict, gold_pages: list[int], document_id: str, k: int = 10) -> float:
    if not gold_pages:
        return 1.0
    returned_pages = {
        page for doc, page in result["hit_pages"][:k] if doc == document_id
    }
    return len(returned_pages & set(gold_pages)) / len(set(gold_pages))


def _expansion_recall_lift(db: Session, label: dict, k: int) -> float:
    """Recall@k with expansion minus recall without (R-05 expansion gate)."""
    from eval.metrics import recall_at_k

    gold_chunks = set(label.get("gold_chunk_ids") or [])
    if not gold_chunks:
        return 0.0

    doc_ids = [label["document_id"]] if label.get("document_id") else None
    settings.enable_query_expansion = False
    raw = run_gold_label(db, label)
    raw_r = recall_at_k(raw["hit_ids"], gold_chunks, k)

    settings.enable_query_expansion = True
    expanded = run_gold_label(db, label)
    exp_r = recall_at_k(expanded["hit_ids"], gold_chunks, k)

    settings.enable_query_expansion = False
    return max(0.0, exp_r - raw_r)


def _header_only_top4(result: dict) -> bool:
    """True if all top-4 hits are header-only (<40 chars)."""
    lens = result.get("hit_text_lens", [])[:4]
    if not lens:
        return False
    return all(length < _MIN_SUBSTANTIVE_CHARS for length in lens)


def build_scorecard(db: Session, gold_path: Path) -> dict:
    from eval.metrics import document_match_rate, recall_at_k

    settings.enable_llm_query_understanding = False
    settings.enable_context_ranker = False
    settings.enable_excerpt_selector = False

    labels = load_gold_labels(gold_path)
    results = []
    scores: dict[str, float] = {}

    simple_labels = [l for l in labels if l.get("mode") == "SIMPLE"]
    for label in simple_labels:
        result = run_gold_label(db, label)
        is_overview = (result.get("diagnostics") or {}).get("intent") == "case_overview"
        recall_k = _OVERVIEW_RECALL_K if is_overview else 10
        page_k = _OVERVIEW_RECALL_K if is_overview else 10

        gold_chunks = set(label.get("gold_chunk_ids") or [])
        if gold_chunks:
            r = recall_at_k(result["hit_ids"], gold_chunks, recall_k)
            scores[f"R-01_{label['query_id']}"] = r
        if label.get("document_id") and not label.get("must_refuse"):
            drm = document_match_rate(
                [h[0] for h in result["hit_pages"]],
                label["document_id"],
            ) if result["hit_pages"] else 0.0
            scores[f"R-03_{label['query_id']}"] = drm
        gold_pages = label.get("gold_pages") or []
        if gold_pages and isinstance(gold_pages[0], int) and not label.get("must_refuse"):
            pr = _page_recall(result, gold_pages, label["document_id"], k=page_k)
            key = "R-05-page" if label.get("query_id", "").startswith("chester_chat") else "R-05"
            scores[f"{key}_{label['query_id']}"] = pr
        is_paraphrase = (
            label.get("variant_group") == "paraphrase"
            or label.get("query_id") in _PARAPHRASE_BENCH_IDS
        )
        if is_paraphrase and gold_chunks and not label.get("must_refuse"):
            exp_lift = _expansion_recall_lift(db, label, recall_k)
            scores[f"R-05-expansion_{label['query_id']}"] = exp_lift
        if label.get("query_id", "").startswith("chester_chat") and not label.get("must_refuse"):
            scores[f"R-05b_{label['query_id']}"] = 0.0 if _header_only_top4(result) else 1.0
        if label.get("must_refuse"):
            scores[f"F-01_{label['query_id']}"] = 1.0 if result["refused"] else 0.0
        results.append(result)

    carp_labels = [l for l in labels if l.get("mode") == "MULTI_CONSTRAINT"]
    for label in carp_labels:
        result = run_gold_label(db, label)
        if label.get("must_refuse"):
            scores[f"F-01_{label['query_id']}"] = 1.0 if result["refused"] else 0.0
        results.append(result)

    critical = {
        k: v
        for k, v in scores.items()
        if "chester_chat" in k or "chester_bench" in k or k.startswith("F-01")
    }
    tier_a_pass = all(v >= 0.5 for v in critical.values()) if critical else True
    return {"results": results, "scores": scores, "tier_a_pass": tier_a_pass, "critical_scores": critical}
