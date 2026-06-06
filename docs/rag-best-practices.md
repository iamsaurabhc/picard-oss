# RAG best practices (Picard-OSS)

Implementation notes from [Enhancing RAG: A Study of Best Practices](https://arxiv.org/html/2501.07391v1) (arXiv:2501.07391v1), adapted for legal FTS5 + CARP.

## Enabled techniques

| Technique | Config | Notes |
|-----------|--------|-------|
| Query expansion | `ENABLE_QUERY_EXPANSION=true` | Broad OR passes before anchor FTS; TTL cache |
| Focus Mode excerpts | `ENABLE_FOCUS_EXCERPTS=true` | Sentence-level scoring in `excerpt_selector` (disabled for entity listing via `listing_disable_focus_excerpts` — page-level context needs full page coherence) |
| Contrastive prompts | `PROMPT_VARIANT=help_v2` | Static good/bad examples in `app/prompts/legal_rag.py` |
| FactVerifier lite | always on in `validate_response` | Strips unsupported amounts/dates vs cited preview |
| Citation judge | `ENABLE_CITATION_JUDGE` | `CITATION_JUDGE_FAIL_CLOSED` for factual intents |
| Hybrid retrieval | `ENABLE_HYBRID_SEARCH=true` (default) | FTS-first RRF + normalized BLOB vectors + `page_embeddings`; run `./scripts/backfill-embeddings.sh --vec-index` after enabling |

### Hybrid setup

```bash
# backend/.env
ENABLE_HYBRID_SEARCH=true

./scripts/start.sh                    # downloads ONNX model on first run
# or: cd backend && python scripts/download_embedding_model.py
./scripts/backfill-embeddings.sh      # index existing parsed PDFs
./scripts/backfill-embeddings.sh --vec-index   # also mean-pool page vectors
python scripts/backfill_embeddings.py --vec-ann   # sqlite-vec ANN (requires apsw on Python 3.13+)
```

## Chat latency profile

Setting: `chat_latency_profile` (`quality` | `balanced` | `fast`) in Settings or `settings.json`.

| Profile | Behavior |
|---------|----------|
| **quality** | Full SLM pipeline: context ranker, excerpt selector, query expansion, planner repair, lower map-reduce thresholds |
| **balanced** (default) | Skips non-critical SLM steps above; raises map-reduce min docs; enables fast-tier anchor FTS for simple/auto queries |
| **fast** | Same SLM skips as balanced; tighter map caps; defers page-vector hybrid where safe |

Diagnostics: each chat `retrieval` SSE event includes `diagnostics.latency_ms` (phase timers + `synthesis_ttft`). Benchmark with `python scripts/benchmark_chat_ttft.py` and compare profiles via `python scripts/eval_latency_profiles.py`.


- **Retrieval stride** during generation — hurts coherence; not used.
- **Multilingual KB** — not applicable to v1 English legal corpus.
- **Contrastive ICL as retrieval KB** — replaced with static prompt exemplars (no eval leakage).

## Eval metrics

- `R-05-page_*` — page recall (chat gold)
- `R-05-expansion_*` — recall lift with expansion (`chester_bench_002`, `chester_bench_003`)
- Tier A gates in `backend/eval/runner.py`

## Agent mode (kernel-first)

Agent chat (`mode=agent`) uses **`stream_chat` with `mode=agent`** — the same Citation Kernel path as RAG mode. There is no second LLM paraphrase or post-tool fallback for vault Q&A.

| Paper technique | Agent behavior |
|-----------------|----------------|
| Query expansion | Forced on during agent retrieval (`retrieve_for_agent`) |
| Focus excerpts | Forced on during agent retrieval |
| Breadth policy | `agent_retrieval_policy.py`: `catalog` / `matter_deep` / `pinpoint` from intent + scoped doc count |
| Persona | `firm` vs `court` caps and prompt tone (`firm_agent_*` / `court_agent_*` settings) |
| Contrastive prompts | `synthesis_mode=agent` + per-profile overlays in `citations.py` |
| Listing map-reduce | Scoped `document_ids` always included in discovery union |
| Page-level listing context | `entity_page_context.py` | Entity-ranked full pages; map-reduce when ≥ `listing_map_reduce_min_docs` (default 4) |
| Hybrid dense+sparse | Same as Chat — enable `ENABLE_HYBRID_SEARCH` when embeddings are backfilled |

**Tier A invariant:** Every agent answer streams `content` with `[N]` markers and a `references` event before `done`.

**Tools:** `answer_from_corpus` / `search_corpus` remain for workflow steps (LightFlow), not the primary Agent chat author.

**Intent:** Queries like `list all case details involving google v CUTS` route to `entity_matter_listing` (not `case_overview`) even when a `v` pattern is present.

## Benchmarks

```bash
cd backend && source .venv/bin/activate
python scripts/benchmark_search.py
python -m pytest tests/test_focus_excerpt.py tests/test_query_expansion.py tests/test_citations.py tests/test_query_understanding_case_v.py tests/test_agent_tools_citations.py tests/test_lightagent_hybrid_gate.py -q
```
