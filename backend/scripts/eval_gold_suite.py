#!/usr/bin/env python3
"""Taxonomy scorecard: PLN-01, COV-01/02/03 by query_family and query_style."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.schemas import SearchRequest
from app.services.context_coverage import apply_context_coverage
from app.services.context_ranker import rank_context
from app.services.overview_retrieval import overview_retrieve
from app.services.query_understanding import understand_query
from app.services.search import execute_search
from eval.coverage_metrics import cov01_pass, cov02_pass, facet_recall, planner_intent_match
from eval.runner import load_gold_labels
from scripts.eval_context_coverage import _configure_flags, open_eval_session


def _filter_labels(labels: list[dict], *, style: str, include_diagnostic: bool) -> list[dict]:
    if include_diagnostic:
        return labels
    if style == "natural_only":
        return [
            l for l in labels
            if l.get("query_style", "natural_only") != "diagnostic"
        ]
    return labels


def main() -> int:
    parser = argparse.ArgumentParser(description="Gold suite taxonomy report")
    parser.add_argument("--labels", default="eval/gold_labels.jsonl")
    parser.add_argument("--style", default="natural_only", choices=["natural_only", "all"])
    parser.add_argument("--include-diagnostic", action="store_true")
    parser.add_argument("--slm", action="store_true")
    args = parser.parse_args()

    _configure_flags(slm_track=args.slm)
    settings.enable_context_expansion = True

    labels = load_gold_labels(Path(args.labels))
    labels = _filter_labels(
        labels,
        style=args.style,
        include_diagnostic=args.include_diagnostic,
    )

    failures = 0
    by_family: dict[str, list[float]] = defaultdict(list)
    metrics: dict[str, float] = {}

    with open_eval_session() as db:
        for label in labels:
            if not label.get("workspace_id"):
                continue
            qid = label["query_id"]
            query = label["query"]
            doc_ids = [label["document_id"]] if label.get("document_id") else None
            ws = label["workspace_id"]

            u = understand_query(query, db=db, workspace_id=ws, document_ids=doc_ids)
            pln = planner_intent_match(u, label)
            if pln is not None:
                metrics[f"PLN-01_{qid}"] = 1.0 if pln else 0.0

            if u.intent == "case_overview":
                hits, diag = overview_retrieve(
                    db, u, workspace_id=ws, document_ids=doc_ids, query=query,
                )
                ranked, rank_diag = rank_context(
                    query, u, hits, top_k=settings.chat_overview_top_k, rank_mode="coverage",
                )
                final, cov_diag = apply_context_coverage(
                    db, ranked, u,
                    query=query, workspace_id=ws, document_ids=doc_ids,
                    top_k=settings.chat_overview_top_k, rank_diagnostics=rank_diag,
                )
                ok = (
                    (len(final) == 0 and label.get("must_refuse"))
                    or (cov02_pass(final) and not label.get("must_refuse"))
                )
                if not label.get("must_refuse"):
                    metrics[f"COV-02_{qid}"] = 1.0 if cov02_pass(final) else 0.0
            else:
                result = execute_search(
                    db,
                    SearchRequest(query=query, workspace_id=ws, document_ids=doc_ids, top_k=24),
                )
                if label.get("must_refuse"):
                    ok = result.refused or len(result.hits) == 0
                else:
                    ranked, rank_diag = rank_context(
                        query, u, result.hits, top_k=12,
                        rank_mode="precision" if u.intent == "factual_lookup" else "coverage",
                    )
                    final, cov_diag = apply_context_coverage(
                        db, ranked, u,
                        query=query, workspace_id=ws, document_ids=doc_ids,
                        bundles=result.bundles,
                        top_k=12, rank_diagnostics=rank_diag,
                    )
                    ok = len(final) > 0
                    if u.sub_questions or label.get("facets"):
                        ok = ok and cov01_pass(final, u, rank_diag)
                        metrics[f"COV-01_{qid}"] = 1.0 if cov01_pass(final, u, rank_diag) else 0.0
                    if label.get("facets"):
                        fr = facet_recall(
                            final,
                            label,
                            coverage_report=cov_diag.get("coverage_report"),
                        )
                        metrics[f"COV-03_{qid}"] = fr
                        ok = ok and fr >= 0.85

            family = label.get("query_family", "legacy")
            by_family[family].append(1.0 if ok else 0.0)
            status = "PASS" if ok else "FAIL"
            print(f"{status} {qid} family={family} intent={u.intent}")
            if not ok:
                failures += 1

    print("\n--- By query_family ---")
    for family, scores in sorted(by_family.items()):
        avg = sum(scores) / len(scores) if scores else 0.0
        print(f"  {family}: {avg:.2f} ({sum(scores):.0f}/{len(scores)})")

    pln_scores = [v for k, v in metrics.items() if k.startswith("PLN-01_")]
    if pln_scores:
        print(f"PLN-01 avg: {sum(pln_scores) / len(pln_scores):.2f}")
    cov03 = [v for k, v in metrics.items() if k.startswith("COV-03_")]
    if cov03:
        print(f"COV-03 avg: {sum(cov03) / len(cov03):.2f}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
