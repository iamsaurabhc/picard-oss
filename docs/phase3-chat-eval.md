# Phase 3 chat evaluation (Tier C + automated chat harness)

## Automated retrieval (Tier A)

Chester NL chat gold rows in `backend/eval/gold_labels.jsonl`:

| query_id | Query | Gate |
|----------|-------|------|
| `chester_chat_001` | List all case details involving Chester v Waverley | R-05 page recall; R-05b no header-only top-4 |
| `chester_chat_002` | What damages did the plaintiff claim? | R-01 chunk recall |
| `chester_chat_003` | Chester v Waverley negligence facts | R-05 page recall; R-05b |
| `chester_chat_ab01` | Unanswerable liability cap | AB-01 refuse |

```bash
cd backend
source .venv/bin/activate
python scripts/eval_scorecard.py
python scripts/eval_chat_chester.py
python -m pytest tests/test_query_understanding.py tests/test_context_ranker.py tests/test_citations.py -q
```

## Pipeline (Phase 3 completion)

1. **Query understanding** — LLM structured plan (`query_understanding.py`) + deterministic FTS builder
2. **Retrieval** — FTS5 or CARP from plan (no free-text expansion heuristics)
3. **Context ranker** — LLM filters header-only chunks before citation map
4. **Synthesis** — enriched prompts with document name + pinpoint quote; `[N]` pills
5. **Optional citation judge** — `ENABLE_CITATION_JUDGE=true` when SLM configured

## Manual Tier C checklist

Run against Chester v Waverley corpus with live LLM:

- [ ] CT-01: pytest `test_citations.py` green
- [ ] CT-02: 10 claims × pinpoint accuracy ≥ 90% (click `[N]` → bbox aligns)
- [ ] Chester demo: "What damages did the plaintiff claim?" → substantive answer citing page 3
- [ ] Chester demo: "List all case details involving Chester v Waverley" → not header-only refusal
- [ ] L-05: 5 citation pills navigate to correct PDF bbox
- [ ] Streaming smoke: Ollama and OpenAI providers

## Config flags

```
ENABLE_LLM_QUERY_UNDERSTANDING=true   # alias: ENABLE_QUERY_EXPANSION
ENABLE_CONTEXT_RANKER=true
ENABLE_CITATION_JUDGE=false
CHAT_RETRIEVAL_POOL_K=24
CHAT_TOP_K=12
CHAT_MAX_CHUNKS_PER_DOC=6
CHAT_OVERVIEW_POOL_K=40
CHAT_OVERVIEW_TOP_K=20
CHAT_OVERVIEW_MAX_CHUNKS_PER_PAGE=2
```

## Case overview (Tier B)

```bash
python scripts/eval_chat_overview.py
python -m pytest tests/test_query_understanding_overview_intent.py tests/test_overview_retrieval_page_diversity.py tests/test_overview_prompt_sections.py -q
```

Overview queries (`list all case details…`) use multi-pass retrieval + coverage ranker + structured synthesis sections.

## Exit criteria (leave Phase 3)

- Tier A passes on `chester_chat_*` gold (including R-05b)
- `eval_chat_chester.py` passes with mocked synthesis
- CT-02 manual ≥ 90% on 10 samples
- Chester v Waverley demo: substantive answer + clickable `[N]` to page 3 damages
