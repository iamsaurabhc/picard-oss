# Evaluation query taxonomy

Gold labels in `backend/eval/gold_labels.jsonl` drive Tier A retrieval and context coverage gates.

## Principles

- **Queries** read like lawyer chat — no CARP templates, canonical ingest strings, or verbatim chunk echoes in `natural_only` rows.
- **Gold** lives in annotation fields: `gold_pages`, `gold_chunk_ids`, `facets[]`, `expected_intent`, `constraints` (CARP unit tests only).

## Schema fields

| Field | Purpose |
|-------|---------|
| `query` | Text passed to planner and retrieval |
| `query_style` | `natural_only` (CI default) or `diagnostic` (benchmark regression) |
| `query_family` | Taxonomy bucket for scorecard breakdown |
| `expected_intent` | Planner-blind intent label for PLN-01 |
| `facets[]` | Sub-parts with `label`, `gold_pages`, `required` for COV-03 |
| `variant_group` | Links paraphrase ladder rows (R-05) |
| `diagnostic_query` | Optional copy-paste baseline (not used in default CI) |

## Query families

- `pinpoint_fact` — single amount/name/date
- `compound_factual` — multiple sub-parts (COV-01)
- `role_party` — who sued whom
- `overview` — case narrative (COV-02)
- `legal_issue` — topic pages (negligence, shock, trespasser)
- `citation_precedent` — precedent discussion without case name in query
- `carp_indirect` — conjunctive context without `"case context for"`
- `carp_negative` / `unanswerable` — refuse (F-01 / AB-01)

## Commands

```bash
cd backend
python scripts/annotate_gold.py
python scripts/eval_scorecard.py
python scripts/eval_context_coverage.py
python scripts/eval_gold_suite.py --style natural_only
python -m pytest tests/test_context_coverage_expansion.py tests/test_carp_bundle_includes_page_chunks.py -q
```

## Corpus annotations

`backend/eval/gold_annotations.jsonl` maps `fact_id` → chunk/page evidence. Re-ingest refresh: `export_test_corpus.py` then update chunk IDs from annotations.

## Tier C chat rubrics

`backend/eval/gold_chat_labels.jsonl` holds end-to-end answer expectations (`required_claims`, `min_citations`) for manual review.
