# Picard OSS

**Local-first legal document AI for legal engineers** — upload PDFs, search with FTS5 or multi-constraint CARP retrieval, and chat with **bbox-grounded citations** that refuse when evidence is missing.

Run everything on your machine. Documents stay under `.picard-data/`. No Neo4j, no Supabase, no cloud OCR bills.

> **Need production SaaS?** [Picard.law](https://picard.law) is the hosted enterprise product built on the same evidence-first principles — GraphRAG, managed infra, and firm-grade deployment. **Picard OSS** is the open-source, single-machine stack for evaluation, integration, and air-gapped workflows.

---

## What you get (Phases 0–3 complete)

| Phase | Status | Highlights |
|-------|--------|------------|
| **0 — Scaffolding** | ✅ | Monorepo, `./scripts/start.sh`, health checks |
| **1 — Ingestion** | ✅ | PDF upload → liteparse chunks + bbox, FTS5 index, entity index for CARP |
| **2 — Relevance engine** | ✅ | BM25 search, query understanding, CARP bundles, eval harness |
| **3 — Citation chat** | ✅ | Streaming Q&A, refuse gate, `[N]` pills → PDF highlight, hybrid entity extraction |

**Planned:** Phase 4 tabular review (Mike-inspired column extraction), Phase 5 OSS polish.

Full design: [ARCHITECTURE.md](ARCHITECTURE.md)

---

## Prerequisites

| Requirement | Version |
|-------------|---------|
| Python | 3.11+ |
| Node.js | 18+ |
| OS | macOS or Linux (Windows via WSL) |

**Optional (recommended for chat & query understanding):**

- [OpenAI API key](https://platform.openai.com/api-keys) — default provider (`gpt-4o-mini`)
- [Ollama](https://ollama.com/) — fully local LLM (`llama3.2`, etc.)

**Optional (scanned PDFs):**

- PaddleOCR sidecar — see [OCR guide](#ocr-for-scanned-pdfs) below

---

## Quick start

```bash
git clone https://github.com/iamsaurabhc/picard-oss.git
cd picard-oss

cp .env.example backend/.env
grep NEXT_PUBLIC .env.example > frontend/.env.local

# Required for chat, query understanding, and SLM entity extract (recommended)
# Edit backend/.env and set:
#   OPENAI_API_KEY=sk-...

chmod +x scripts/start.sh scripts/eval-search.sh
./scripts/start.sh
```

| Service | URL |
|---------|-----|
| Workspaces (upload PDFs) | http://localhost:3000/workspaces |
| Search (FTS5 + CARP debug) | http://localhost:3000/search |
| Citation chat | http://localhost:3000/chat |
| API health | http://localhost:8000/health |
| OpenAPI docs | http://localhost:8000/docs |

### First workflow (5 minutes)

1. Open **Workspaces** → create a workspace (e.g. `Chester eval`).
2. Upload a PDF (text-native works out of the box; scanned PDFs need [OCR](#ocr-for-scanned-pdfs)).
3. Wait for `parse_status=done` on the document row.
4. Open **Search** — try `"plaintiff claimed damages"` (simple FTS5) or a multi-entity query (CARP).
5. Open **Chat** — attach workspace documents, ask a question, click `[1]` to jump to the bbox in the PDF viewer.

Eval corpus (Chester v Municipality of Waverly, 627 chunks) ships in tests — see [Testing](#testing--evaluation).

---

## API keys & LLM configuration

Copy [`.env.example`](.env.example) to `backend/.env`. The frontend only needs `NEXT_PUBLIC_API_URL`.

### OpenAI (default)

```bash
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=sk-...
```

Powers: chat synthesis, structured query understanding, optional SLM entity extract (`ENABLE_SLM_ENTITY_EXTRACT=true`), context ranker.

### Ollama (fully local)

```bash
LLM_PROVIDER=ollama
LLM_MODEL=llama3.2
OLLAMA_BASE_URL=http://localhost:11434
# OPENAI_API_KEY not required
```

Pull a model first: `ollama pull llama3.2`

### Tiered models (optional)

Route cheap work to an SLM and synthesis to a larger model:

```bash
ENABLE_TIERED_MODELS=true
SLM_MODEL=gpt-4o-mini          # or openrouter/meta-llama/llama-3.2-3b-instruct:free
LLM_MODEL=gpt-4o               # synthesis
ENABLE_CITATION_JUDGE=true     # optional post-gen validation when SLM configured
```

### Feature flags (legal-engineering defaults)

```bash
ENABLE_CARP=true                          # multi-constraint retrieval
ENABLE_LLM_QUERY_UNDERSTANDING=true       # structured query plan (not raw expansion)
ENABLE_CONTEXT_RANKER=true                # filter header-only chunks before synthesis
ENABLE_SLM_ENTITY_EXTRACT=true            # bounded SLM pass per document at ingest
ENABLE_NER_ENTITY_EXTRACT=false           # GLiNER hybrid; enable after ./scripts/entity-ab.sh
ENABLE_METADATA_LLM=false                 # filename rules suffice for most PoCs
```

Chat and search **refuse** (no LLM call) when retrieval returns zero evidence — see [evidence contract](ARCHITECTURE.md#7-evidence-contract-adapted-from-picardlaw).

---

## OCR for scanned PDFs

Picard auto-detects **digital** vs **scan** PDFs (`pdf_text_profile.py`). Digital PDFs parse at 150 DPI with no OCR. Scans use liteparse OCR at 300 DPI.

### Detection & engines

| PDF type | Behavior |
|----------|----------|
| Digital (embedded text) | Direct text extraction, no OCR |
| Scan / image-only | OCR enabled — **PaddleOCR** if server reachable, else **Tesseract** fallback |

Check OCR status:

```bash
curl -s http://localhost:8000/health/ocr | jq
```

### PaddleOCR (recommended for scans)

Start the sidecar alongside the app:

```bash
# Option A — bundled with start.sh
START_PADDLE_OCR=1 ./scripts/start.sh

# Option B — separate terminal
./scripts/start-paddleocr.sh
```

Default endpoint: `http://localhost:8829/ocr` (configured via `LITEPARSE_OCR_SERVER_URL` in `backend/.env`).

First run installs PaddleOCR deps into `backend/.venv` (one-time, a few minutes).

### Environment variables

```bash
LITEPARSE_OCR_SERVER_URL=http://localhost:8829/ocr
LITEPARSE_OCR_LANGUAGE=eng
LITEPARSE_DPI_DIGITAL=150
LITEPARSE_DPI_OCR=300
# LITEPARSE_REQUIRE_PADDLEOCR=false   # set true to fail fast if PaddleOCR is down
```

**Tip:** For privilege-sensitive workflows, OCR runs locally — no document bytes leave your machine.

---

## API quick reference

Interactive docs: http://localhost:8000/docs

### Workspaces & documents

```bash
# Create workspace
curl -s -X POST http://localhost:8000/workspaces \
  -H 'Content-Type: application/json' \
  -d '{"name": "Matter Alpha", "matter_ref": "2024-001"}'

# Upload PDF
curl -s -X POST "http://localhost:8000/workspaces/{workspace_id}/documents" \
  -F "file=@contract.pdf"

# Poll parse status
curl -s "http://localhost:8000/documents/{document_id}"
```

### Search (FTS5 + CARP)

```bash
# Simple BM25
curl -s http://localhost:8000/search -H 'Content-Type: application/json' -d '{
  "query": "limitation of liability",
  "workspace_id": "YOUR_WORKSPACE_ID",
  "retrieval_mode": "simple"
}'

# Multi-constraint CARP (party + date + condition intersection)
curl -s http://localhost:8000/search -H 'Content-Type: application/json' -d '{
  "query": "case context for supreme court and refused",
  "workspace_id": "eca7aebb-0b4d-433d-8e73-9144c04eb0d7",
  "retrieval_mode": "multi_constraint"
}'
```

Response includes `chunks`, optional `context_bundles`, and `retrieval_diagnostics` (constraint extraction, page intersection counts, proximity tier).

### Citation chat (SSE)

```bash
# Create session
SESSION=$(curl -s -X POST http://localhost:8000/chat/sessions \
  -H 'Content-Type: application/json' \
  -d '{"workspace_id": "YOUR_WORKSPACE_ID"}' | jq -r .id)

# Stream answer with [N] citations
curl -N http://localhost:8000/chat/stream \
  -H 'Content-Type: application/json' \
  -d "{
    \"session_id\": \"$SESSION\",
    \"workspace_id\": \"YOUR_WORKSPACE_ID\",
    \"message\": \"What damages did the plaintiff claim?\",
    \"retrieval_mode\": \"auto\"
  }"
```

Events: `retrieval` → `content` (tokens) → `done` (references with chunk_id, page, bbox). Refused queries return `refused: true` with suggestions — **no LLM synthesis**.

---

## Architecture at a glance

```
Upload PDF → liteparse (+ OCR if scan) → chunks + bbox + FTS5
                    ↓
         entity extract → page_entities (CARP foundation)
                    ↓
    Search: FTS5 (keyword)  |  CARP (multi-constraint bundles)
                    ↓
    Chat: query plan → retrieve → refuse gate → citation map → stream
                    ↓
         UI: [N] pills → MultiHighlightPDFViewer (bbox overlay)
```

- **FTS5 over vectors** — exact legal phrases beat semantic neighbors for contract/litigation retrieval
- **CARP** — Constraint-Aware Retrieval: page-set intersection for party + date + condition queries without Neo4j
- **Evidence contract** — citations assigned before synthesis; zero-evidence → refuse (inherited from [Picard.law](https://picard.law) / LegalDocX)

Details: [ARCHITECTURE.md](ARCHITECTURE.md) · Phase 2 eval: [docs/phase2-eval.md](docs/phase2-eval.md) · Phase 3 eval: [docs/phase3-eval.md](docs/phase3-eval.md)

---

## Testing & evaluation

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Unit + integration (Chester corpus snapshot)
pytest -m "not slow" -q
pytest -m corpus -q

# Phase 2 search scorecard + Phase 3 chat/entity gates
./scripts/eval-search.sh          # from repo root
python scripts/eval_scorecard.py
python scripts/eval_chat_chester.py
python scripts/eval_entity_ab.py

# Refresh test corpus after entity backfill
python scripts/backfill_entities.py
python scripts/export_test_corpus.py   # → backend/test/fixtures/corpus/
```

**Tier A gates** (automated): R-01/R-05 retrieval recall, C-02/C-09 CARP vs OR-BM25, AB-01 refuse-without-LLM, CT-01 citation map resolution.

**Tier C** (manual legal review): bbox alignment (L-05), pinpoint citation accuracy (CT-02 ≥ 90%). Checklist: [docs/phase3-chat-eval.md](docs/phase3-chat-eval.md).

---

## Picard OSS vs [Picard.law](https://picard.law)

| | **Picard OSS** (this repo) | **[Picard.law](https://picard.law)** |
|--|---------------------------|--------------------------------------|
| Deployment | Single machine, `./scripts/start.sh` | Managed SaaS / enterprise |
| Retrieval | SQLite FTS5 + CARP | GraphRAG + Neo4j |
| Data residency | `.picard-data/` on your disk | Enterprise cloud / on-prem tiers |
| Best for | Legal engineers, PoC, air-gap, AGPL eval | Production, multi-user, firm workflows |
| License | [AGPL-3.0](LICENSE) local use | Commercial |

Building a hosted product on unreleased modifications? See [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md) or contact [saurabh.c@picard.law](mailto:saurabh.c@picard.law).

---

## Licensing

Picard OSS is **local-first**: run on your machine, keep data under `.picard-data/`, evaluate search and citation chat without a commercial agreement.

| Use case | License |
|----------|---------|
| Local dev, personal PoC, evaluation on your hardware | [AGPL-3.0](LICENSE) — no fee |
| Forking, contributing, or redistributing modified versions | AGPL-3.0 — source to users; network use triggers AGPL for SaaS |
| Production, enterprise, OEM, or hosted service **without** AGPL obligations | [Commercial license](COMMERCIAL-LICENSE.md) — [picard.law](https://picard.law) |

---

## Keywords

local-first legal AI · legal document assistant · citation-grade RAG · FTS5 legal search · CARP multi-constraint retrieval · bbox PDF citations · legal engineers · liteparse · refuse gate · evidence-first legal tech · open source legal AI · privilege-safe document AI · contract review OSS
