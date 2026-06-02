#!/usr/bin/env python3
"""Validate gold label rows for anti-leakage and required schema fields."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.runner import load_gold_labels

_CARP_TEMPLATE = re.compile(r"case context for\b", re.I)
_CANONICAL_LEAK = re.compile(r"\b1000_gbp\b|agreement that\b", re.I)
_PAGE_LEAK = re.compile(r"\bpage\s+\d+\b", re.I)


def validate_row(row: dict) -> list[str]:
    errors: list[str] = []
    qid = row.get("query_id", "?")
    query = row.get("query") or ""
    style = row.get("query_style", "natural_only")

    if style == "natural_only":
        if _CARP_TEMPLATE.search(query):
            errors.append(f"{qid}: CARP template in natural query")
        if _CANONICAL_LEAK.search(query):
            errors.append(f"{qid}: canonical entity leak in natural query")
        if _PAGE_LEAK.search(query):
            errors.append(f"{qid}: page number in natural query")
        if "plaintiff claimed damages in the sum" in query.casefold():
            errors.append(f"{qid}: verbatim chunk echo in natural query")

    if row.get("expected_intent") and not row.get("query_family"):
        errors.append(f"{qid}: expected_intent without query_family")

    facets = row.get("facets") or []
    for facet in facets:
        if not facet.get("label"):
            errors.append(f"{qid}: facet missing label")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Gold label anti-leakage linter")
    parser.add_argument("--labels", default="eval/gold_labels.jsonl")
    parser.add_argument("--fix-style", action="store_true", help="Tag legacy diagnostic rows in output")
    args = parser.parse_args()

    path = Path(args.labels)
    labels = load_gold_labels(path)
    all_errors: list[str] = []

    for row in labels:
        all_errors.extend(validate_row(row))

    if all_errors:
        print("Validation errors:")
        for err in all_errors:
            print(f"  - {err}")
    else:
        print(f"OK: {len(labels)} rows passed anti-leakage checks")

    natural = sum(1 for l in labels if l.get("query_style") == "natural_only")
    diagnostic = sum(1 for l in labels if l.get("query_style") == "diagnostic")
    print(f"Counts: natural_only={natural} diagnostic={diagnostic} untagged={len(labels) - natural - diagnostic}")

    return 1 if all_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
