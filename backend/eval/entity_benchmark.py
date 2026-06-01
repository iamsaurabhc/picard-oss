from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.schemas import SearchRequest
from app.services.search import execute_search
from eval.metrics import intersection_recall, recall_at_k
from eval.runner import load_gold_labels


def _gold_pages_set(label: dict) -> set[tuple[str, int]]:
    pages = label.get("gold_pages") or []
    out: set[tuple[str, int]] = set()
    for p in pages:
        if isinstance(p, dict):
            out.add((p["document_id"], int(p["page_number"])))
        elif label.get("document_id"):
            out.add((label["document_id"], int(p)))
    return out


def score_benchmark_label(db: Session, label: dict) -> dict:
    body = SearchRequest(
        query=label["query"],
        workspace_id=label["workspace_id"],
        document_ids=[label["document_id"]] if label.get("document_id") else None,
        retrieval_mode="multi_constraint" if label.get("mode") == "MULTI_CONSTRAINT" else "simple",
        allow_partial_disclosure=label.get("allow_partial", False),
    )
    if label.get("mode") == "MULTI_CONSTRAINT":
        body.retrieval_mode = "multi_constraint"
    response = execute_search(db, body)
    hit_pages = {(h.document_id, h.page_number) for h in response.hits}
    gold_pages = _gold_pages_set(label)
    gold_chunks = set(label.get("gold_chunk_ids") or [])

    scores: dict[str, float] = {}
    if label.get("must_refuse"):
        scores["f01"] = 1.0 if response.refused else 0.0
    elif gold_pages:
        scores["c02"] = intersection_recall(hit_pages, gold_pages)
    if gold_chunks:
        scores["r01"] = recall_at_k([h.chunk_id for h in response.hits], gold_chunks, 10)

    return {
        "query_id": label["query_id"],
        "mode": response.mode,
        "refused": response.refused,
        "hit_count": len(response.hits),
        "scores": scores,
        "entity_sensitive": label.get("entity_sensitive", False),
    }


def run_benchmark(db: Session, path: Path) -> dict:
    labels = load_gold_labels(path)
    per_query = [score_benchmark_label(db, label) for label in labels]

    def _agg(key: str) -> float:
        vals = [q["scores"][key] for q in per_query if key in q["scores"]]
        return sum(vals) / len(vals) if vals else 0.0

    def _pass_count(key: str, threshold: float = 0.5) -> int:
        return sum(1 for q in per_query if q["scores"].get(key, 0) >= threshold)

    entity_labels = [q for q in per_query if q.get("entity_sensitive")]
    return {
        "per_query": per_query,
        "aggregate": {
            "r01_mean": _agg("r01"),
            "c02_mean": _agg("c02"),
            "f01_mean": _agg("f01"),
            "c02_pass": _pass_count("c02"),
            "f01_pass": _pass_count("f01"),
            "r01_pass": _pass_count("r01"),
            "entity_c02_pass": sum(
                1 for q in entity_labels if q["scores"].get("c02", 0) >= 0.5 or q["scores"].get("f01", 0) == 1.0
            ),
            "total": len(per_query),
        },
    }


def compare_ab(rules: dict, hybrid: dict) -> dict:
    rules_agg = rules["aggregate"]
    hybrid_agg = hybrid["aggregate"]
    return {
        "rules": rules_agg,
        "hybrid": hybrid_agg,
        "delta": {
            "c02_pass": hybrid_agg["c02_pass"] - rules_agg["c02_pass"],
            "f01_pass": hybrid_agg["f01_pass"] - rules_agg["f01_pass"],
            "r01_pass": hybrid_agg["r01_pass"] - rules_agg["r01_pass"],
            "c02_mean": round(hybrid_agg["c02_mean"] - rules_agg["c02_mean"], 4),
            "r01_mean": round(hybrid_agg["r01_mean"] - rules_agg["r01_mean"], 4),
        },
        "entity_ab_pass": hybrid_agg["c02_pass"] >= rules_agg["c02_pass"]
        and hybrid_agg["f01_pass"] >= rules_agg["f01_pass"]
        and hybrid_agg["r01_pass"] >= rules_agg["r01_pass"],
        "recommend_enable_ner": hybrid_agg["entity_c02_pass"] > rules_agg["entity_c02_pass"]
        or hybrid_agg["r01_mean"] > rules_agg["r01_mean"],
    }


def format_markdown_report(comparison: dict, *, hybrid_available: bool) -> str:
    lines = [
        "# Phase 3 entity extraction A/B report",
        "",
        f"Hybrid NER available: **{hybrid_available}**",
        "",
        "## Aggregate",
        "",
        "| Metric | Rules | Hybrid | Delta |",
        "|--------|-------|--------|-------|",
    ]
    r = comparison["rules"]
    h = comparison["hybrid"]
    d = comparison["delta"]
    lines.append(f"| C-02 pass count | {r['c02_pass']} | {h['c02_pass']} | {d['c02_pass']:+d} |")
    lines.append(f"| F-01 pass count | {r['f01_pass']} | {h['f01_pass']} | {d['f01_pass']:+d} |")
    lines.append(f"| R-01 pass count | {r['r01_pass']} | {h['r01_pass']} | {d['r01_pass']:+d} |")
    lines.append(f"| C-02 mean | {r['c02_mean']:.3f} | {h['c02_mean']:.3f} | {d['c02_mean']:+.3f} |")
    lines.append(f"| R-01 mean | {r['r01_mean']:.3f} | {h['r01_mean']:.3f} | {d['r01_mean']:+.3f} |")
    lines.append("")
    lines.append(f"**entity_ab_pass:** {comparison['entity_ab_pass']}")
    lines.append(f"**recommend_enable_ner:** {comparison['recommend_enable_ner']}")
    return "\n".join(lines)
