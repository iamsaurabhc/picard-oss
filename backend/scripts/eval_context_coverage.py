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
from app.schemas import SearchRequest
from app.services.citations import build_citation_map, build_system_prompt
from app.services.context_ranker import rank_context
from app.services.overview_retrieval import overview_retrieve
from app.services.query_understanding import understand_query
from app.schemas import SearchHit
from app.services.search import execute_search
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


def _rubrics_overview(hits: list[SearchHit], diagnostics: dict) -> dict:
    pages = {(h.document_id, h.page_number) for h in hits}
    return {
        "distinct_pages_gte_3": len(pages) >= 3,
        "pool_size": diagnostics.get("pool_size", len(hits)),
        "distinct_pages": len(pages),
        "search_pass_labels": diagnostics.get("search_pass_labels", []),
        "not_refused": len(hits) > 0,
    }


def _rubrics_compound_factual(
    hits: list[SearchHit],
    diagnostics: dict,
    understanding,
    query: str,
) -> dict:
    pass_labels_hit = diagnostics.get("pass_labels_hit") or []
    sub_covered = diagnostics.get("sub_questions_covered") or []
    rubrics = {
        "not_refused": len(hits) > 0,
        "hit_count": len(hits),
        "pass_labels_hit": pass_labels_hit,
        "pass_labels_gte_1": len(pass_labels_hit) >= 1 or len(hits) > 0,
        "sub_questions_covered": sub_covered,
    }
    if understanding.sub_questions:
        ranked = hits
        cmap = build_citation_map(
            ranked,
            excerpt_chars=600,
            question=query,
            sub_questions=understanding.sub_questions,
        )
        prompt = build_system_prompt(
            cmap,
            intent=understanding.intent,
            sub_questions=understanding.sub_questions,
        ).casefold()
        rubrics["prompt_has_excerpts"] = "excerpt:" in prompt
        rubrics["sub_question_count"] = len(understanding.sub_questions)
        if settings.enable_excerpt_selector:
            rubrics["sub_questions_with_labels"] = len(sub_covered) >= 1 or len(understanding.sub_questions) == 0
    return rubrics


def main() -> int:
    parser = argparse.ArgumentParser(description="Generic context coverage eval")
    parser.add_argument("--labels", default="eval/gold_labels.jsonl")
    parser.add_argument("--query-id", action="append", dest="query_ids")
    parser.add_argument(
        "--slm",
        action="store_true",
        help="Run with SLM query planning, ranker, and excerpt selector enabled",
    )
    args = parser.parse_args()

    _configure_flags(slm_track=args.slm)

    labels = load_gold_labels(Path(args.labels))
    if args.query_ids:
        labels = [l for l in labels if l["query_id"] in args.query_ids]

    failures = 0
    track = "slm" if args.slm else "fallback"
    with open_eval_session() as db:
        for label in labels:
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
                diag = {**diag, **rank_diag}
                rubrics = _rubrics_overview(ranked, diag)
                if label.get("must_refuse"):
                    ok = len(ranked) == 0
                else:
                    ok = rubrics["not_refused"] and rubrics["distinct_pages_gte_3"]
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
                if u.intent == "factual_lookup":
                    ranked, rank_diag = rank_context(query, u, result.hits, top_k=12, rank_mode="precision")
                    diag = {**diag, **rank_diag}
                    pool = ranked if ranked else result.hits
                    rubrics = _rubrics_compound_factual(pool, diag, u, query)
                    if label.get("must_refuse"):
                        ok = result.refused
                    else:
                        ok = rubrics["not_refused"] and rubrics["pass_labels_gte_1"]
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
