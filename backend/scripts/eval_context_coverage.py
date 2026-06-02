#!/usr/bin/env python3
"""Generic context coverage rubrics — deterministic fallback and optional SLM track."""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.bootstrap import run_migrations
from app.schemas import SearchHit, SearchRequest
from app.services.citations import build_citation_map, build_system_prompt
from app.services.context_coverage import apply_context_coverage
from app.services.context_ranker import rank_context
from app.services.overview_retrieval import overview_retrieve
from app.services.query_understanding import understand_query
from app.services.search import execute_search
from eval.coverage_metrics import cov01_pass, cov02_pass, facet_recall
from eval.runner import load_gold_labels
from tests.conftest import resolve_corpus_db_path


@contextmanager
def open_eval_session():
    path = resolve_corpus_db_path()
    if not path:
        raise SystemExit("No corpus DB found; run export_test_corpus.py or use .picard-data/picard.db")
    url = f"sqlite:///{path}"
    engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    run_migrations(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _configure_flags(*, slm_track: bool) -> None:
    settings.enable_llm_query_understanding = slm_track
    settings.enable_context_ranker = slm_track
    settings.enable_excerpt_selector = slm_track
    settings.query_planner_repair_on_zero_hits = slm_track
    settings.enable_context_expansion = True


def _rubrics_overview(hits: list[SearchHit], diagnostics: dict) -> dict:
    pages = {(h.document_id, h.page_number) for h in hits}
    return {
        "COV-02": cov02_pass(hits),
        "distinct_pages_gte_3": len(pages) >= 3,
        "pool_size": diagnostics.get("pool_size", len(hits)),
        "distinct_pages": len(pages),
        "context_chunk_count": diagnostics.get("context_chunk_count", len(hits)),
        "not_refused": len(hits) > 0,
    }


def _rubrics_compound_factual(
    hits: list[SearchHit],
    diagnostics: dict,
    understanding,
    query: str,
    label: dict,
) -> dict:
    coverage = diagnostics.get("coverage_report") or {}
    sub_covered = list((coverage.get("sub_question_coverage") or {}).keys())
    rubrics = {
        "COV-01": cov01_pass(hits, understanding, diagnostics),
        "not_refused": len(hits) > 0,
        "hit_count": len(hits),
        "sub_questions_covered": sub_covered,
        "expansion_added": diagnostics.get("expansion_added", 0),
    }
    if label.get("facets"):
        rubrics["COV-03"] = facet_recall(hits, label, coverage_report=coverage)
    if understanding.sub_questions:
        cmap = build_citation_map(
            hits,
            excerpt_chars=600,
            question=query,
            sub_questions=understanding.sub_questions,
        )
        prompt = build_system_prompt(
            cmap,
            intent=understanding.intent,
            sub_questions=understanding.sub_questions,
            sub_question_coverage=coverage.get("sub_question_coverage"),
        ).casefold()
        rubrics["prompt_has_excerpts"] = "excerpt:" in prompt
        rubrics["sub_question_count"] = len(understanding.sub_questions)
    return rubrics


def _filter_labels(labels: list[dict], include_diagnostic: bool) -> list[dict]:
    if include_diagnostic:
        return labels
    return [l for l in labels if l.get("query_style") != "diagnostic"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generic context coverage eval")
    parser.add_argument("--labels", default="eval/gold_labels.jsonl")
    parser.add_argument("--query-id", action="append", dest="query_ids")
    parser.add_argument("--include-diagnostic", action="store_true")
    parser.add_argument(
        "--slm",
        action="store_true",
        help="Run with SLM query planning, ranker, and excerpt selector enabled",
    )
    args = parser.parse_args()

    _configure_flags(slm_track=args.slm)

    labels = load_gold_labels(Path(args.labels))
    labels = _filter_labels(labels, args.include_diagnostic)
    if args.query_ids:
        labels = [l for l in labels if l["query_id"] in args.query_ids]

    failures = 0
    track = "slm" if args.slm else "fallback"
    with open_eval_session() as db:
        for label in labels:
            if not label.get("workspace_id"):
                continue
            qid = label["query_id"]
            query = label["query"]
            doc_ids = [label["document_id"]] if label.get("document_id") else None
            ws = label["workspace_id"]

            u = understand_query(
                query,
                db=db,
                workspace_id=ws,
                document_ids=doc_ids,
            )
            if u.intent == "case_overview":
                hits, diag = overview_retrieve(
                    db, u, workspace_id=ws, document_ids=doc_ids, query=query,
                )
                ranked, rank_diag = rank_context(query, u, hits, top_k=12, rank_mode="coverage")
                hits, cov_diag = apply_context_coverage(
                    db, ranked, u,
                    query=query, workspace_id=ws, document_ids=doc_ids,
                    top_k=12, rank_diagnostics=rank_diag,
                )
                diag = {**diag, **rank_diag, **cov_diag}
                rubrics = _rubrics_overview(hits, diag)
                if label.get("must_refuse"):
                    ok = len(hits) == 0
                else:
                    ok = rubrics["not_refused"] and rubrics["COV-02"]
            else:
                result = execute_search(
                    db,
                    SearchRequest(
                        query=query,
                        workspace_id=ws,
                        document_ids=doc_ids,
                        top_k=24,
                    ),
                )
                diag = result.retrieval_diagnostics or {}
                if u.intent == "factual_lookup" or label.get("facets"):
                    ranked, rank_diag = rank_context(query, u, result.hits, top_k=12, rank_mode="precision")
                    hits, cov_diag = apply_context_coverage(
                        db, ranked, u,
                        query=query, workspace_id=ws, document_ids=doc_ids,
                        bundles=result.bundles,
                        top_k=12, rank_diagnostics=rank_diag,
                    )
                    diag = {**diag, **rank_diag, **cov_diag}
                    rubrics = _rubrics_compound_factual(hits, diag, u, query, label)
                    if label.get("must_refuse"):
                        ok = result.refused
                    else:
                        ok = rubrics["not_refused"] and rubrics["COV-01"]
                        if label.get("facets"):
                            ok = ok and rubrics.get("COV-03", 0) >= 0.85
                else:
                    rubrics = {"not_refused": not result.refused and len(result.hits) > 0, "hit_count": len(result.hits)}
                    if label.get("must_refuse"):
                        ok = result.refused
                    else:
                        ok = rubrics["not_refused"]

            status = "PASS" if ok else "FAIL"
            print(f"{status} [{track}] {qid}: {json.dumps(rubrics)}")
            if not ok:
                failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
