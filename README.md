# Phase 2: Relevance engine + CARP

Local-first legal document assistant. Phase 2 adds enhanced FTS5 search, query expansion, CARP multi-constraint retrieval, and a dev search UI.

## Quick start

```bash
cp .env.example backend/.env
grep NEXT_PUBLIC .env.example > frontend/.env.local
# Add OPENAI_API_KEY to backend/.env for query expansion (optional — rules fallback works)
chmod +x scripts/start.sh scripts/eval-search.sh
./scripts/start.sh
```

- Frontend: http://localhost:3000
- Search UI: http://localhost:3000/search
- Backend health: http://localhost:8000/health

## Phase 2 scope

- `POST /search` — SIMPLE (FTS5 + optional expansion) or MULTI_CONSTRAINT (CARP)
- ConstraintQueryPlanner + page intersection + context bundles
- Refuse gate with `retrieval_diagnostics`
- Metadata tags (rule-based + optional LLM pass)
- Eval harness: `backend/eval/gold_labels.jsonl`, Tier A metrics (see ARCHITECTURE.md §15)

## LLM configuration

OpenAI default (in `backend/.env`):

```bash
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-...
```

Ollama alternative:

```bash
LLM_PROVIDER=ollama
LLM_MODEL=llama3.2
OLLAMA_BASE_URL=http://localhost:11434
```

## Tests

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -m "not slow"          # unit + corpus (uses .picard-data or snapshot)
pytest -m corpus              # Chester corpus integration
python scripts/export_test_corpus.py   # snapshot .picard-data → test/fixtures/corpus/
./scripts/eval-search.sh
```

Example CARP query (curl):

```bash
curl -s http://localhost:8000/search -H 'Content-Type: application/json' -d '{
  "query": "case context for supreme court and refused",
  "workspace_id": "eca7aebb-0b4d-433d-8e73-9144c04eb0d7",
  "retrieval_mode": "multi_constraint"
}'
```

## Licensing

Picard OSS is **local-first**: run it on your machine, keep data under `.picard-data/`,
and evaluate search/CARP without a commercial agreement.

| Use case | License |
|----------|---------|
| Local dev, personal PoC, evaluation on your own hardware | [AGPL-3.0](LICENSE) — no fee |
| Forking, contributing, or redistributing (including modified versions) | AGPL-3.0 — comply with copyleft (source to users; network use triggers AGPL for SaaS) |
| Production, enterprise, OEM, or hosted service **without** AGPL obligations | [Commercial license](COMMERCIAL-LICENSE.md) — contact licensor |

**AGPL-3.0** applies to this repository unless you have a separate signed commercial
agreement. If you offer Picard (or a modified version) as a service over a network,
AGPL requires that users can obtain the corresponding source.

For enterprise terms, support, and trademark use, see [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md)
and replace the contact placeholders there with your legal entity.

## Notes

- Phase 2 targets **text-native PDFs**; eval corpus: Chester v Municipality of Waverly (627 chunks)
- Data stored under `.picard-data/` by default
