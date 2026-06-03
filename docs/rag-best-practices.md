# RAG best practices (Picard-OSS)

Implementation notes from [Enhancing RAG: A Study of Best Practices](https://arxiv.org/html/2501.07391v1) (arXiv:2501.07391v1), adapted for legal FTS5 + CARP.

## Enabled techniques

| Technique | Config | Notes |
|-----------|--------|-------|
| Query expansion | `ENABLE_QUERY_EXPANSION=true` | Broad OR passes before anchor FTS; TTL cache |
| Focus Mode excerpts | `ENABLE_FOCUS_EXCERPTS=true` | Sentence-level scoring in `excerpt_selector` |
| Contrastive prompts | `PROMPT_VARIANT=help_v2` | Static good/bad examples in `app/prompts/legal_rag.py` |
| FactVerifier lite | always on in `validate_response` | Strips unsupported amounts/dates vs cited preview |
| Citation judge | `ENABLE_CITATION_JUDGE` | `CITATION_JUDGE_FAIL_CLOSED` for factual intents |
| Hybrid retrieval | `ENABLE_HYBRID_SEARCH=false` (default) | FTS-first RRF + `fastembed`; model auto-downloads to `.picard-data/models/fastembed` on `./scripts/start.sh` and at backend startup when enabled |

### Hybrid setup

```bash
# backend/.env
ENABLE_HYBRID_SEARCH=true

./scripts/start.sh                    # downloads ONNX model on first run
# or: cd backend && python scripts/download_embedding_model.py
./scripts/backfill-embeddings.sh      # index existing parsed PDFs
```

## Deferred (paper findings)

- **Retrieval stride** during generation — hurts coherence; not used.
- **Multilingual KB** — not applicable to v1 English legal corpus.
- **Contrastive ICL as retrieval KB** — replaced with static prompt exemplars (no eval leakage).

## Eval metrics

- `R-05-page_*` — page recall (chat gold)
- `R-05-expansion_*` — recall lift with expansion (`chester_bench_002`, `chester_bench_003`)
- Tier A gates in `backend/eval/runner.py`

## Benchmarks

```bash
cd backend && source .venv/bin/activate
python scripts/benchmark_search.py
python -m pytest tests/test_focus_excerpt.py tests/test_query_expansion.py tests/test_citations.py -q
```
