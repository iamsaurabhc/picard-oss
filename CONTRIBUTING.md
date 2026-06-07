# Contributing to Picard OSS

Thank you for your interest in contributing. Picard OSS is a local-first legal document assistant built for legal engineers — citation-grade retrieval, bbox-grounded PDF verification, and evidence-first chat.

This guide covers how to set up a dev environment, run tests, and open a pull request. For installation and architecture details, see the [README](README.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## License

Contributions are accepted under the [AGPL-3.0](LICENSE). By submitting a pull request, you agree that your contribution will be licensed under the same terms.

If you plan to run a hosted service on modified code without AGPL obligations, see [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md).

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Please be respectful and constructive in issues, pull requests, and discussions.

## Quick start

1. Fork and clone the repository.
2. Copy environment files:

   ```bash
   cp .env.example backend/.env
   grep NEXT_PUBLIC .env.example > frontend/.env.local
   ```

3. Start the dev stack:

   ```bash
   ./scripts/start.sh
   ```

   Open [http://localhost:3000](http://localhost:3000). Full prerequisites and troubleshooting: [README — Prerequisites](README.md#prerequisites).

For desktop builds, see [docs/RELEASE.md](docs/RELEASE.md).

## Project layout

| Path | Purpose |
| ---- | ------- |
| `frontend/` | Next.js app (workspaces, search, chat, PDF viewer) |
| `backend/` | FastAPI API, ingestion, FTS5 + CARP, citation chat |
| `desktop/` | Tauri native installers |
| `scripts/` | `start.sh`, eval harness, release helpers |
| `docs/` | Architecture, evaluation guides, release notes |
| `backend/eval/` | Gold labels and eval fixtures |

## Making changes

### Backend

- API routes: `backend/app/routers/`
- Core services: `backend/app/services/` (retrieval, citations, query understanding, etc.)
- Tests: `backend/tests/`

When changing retrieval, CARP, or citation behavior, read [docs/rag-best-practices.md](docs/rag-best-practices.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) first.

### Frontend

- Pages: `frontend/app/`
- Components: `frontend/components/`
- API client: `frontend/lib/picardApi.ts`

### Eval and gold labels

Gold queries live in [backend/eval/gold_labels.jsonl](backend/eval/gold_labels.jsonl). Metric IDs (R/C/F/CT/FG/AB) are documented in the [README — Eval metrics](README.md#eval-metrics--quality-gates).

## Testing before a PR

Run the checks relevant to your change:

```bash
cd backend && source .venv/bin/activate
pytest -m "not slow" -q
pytest -m corpus -q          # required when touching retrieval, CARP, or citations
cd ../frontend && npm run build
```

Additional eval commands (when applicable):

```bash
./scripts/eval-search.sh
python backend/scripts/eval_scorecard.py
python backend/scripts/eval_chat_chester.py
```

| Change type | Minimum checks |
| ----------- | -------------- |
| Backend logic | `pytest -m "not slow"` |
| Retrieval / CARP / citations | `pytest -m corpus` + eval harness if behavior changed |
| Frontend UI | `npm run build` |
| Docs only | Preview rendered markdown |

## Pull request guidelines

1. **One logical change per PR** when possible — easier to review and bisect.
2. **Describe what and why** — include repro steps for bug fixes.
3. **Note eval tier run** — e.g. "pytest corpus pass; eval-search unchanged."
4. **Link related issues** — `Fixes #123` or `Relates to #456`.
5. **No secrets** — never commit API keys, `.env` files, or `.picard-data/` contents.
6. **Follow the PR template** — it includes testing and accessibility checklists.

## Accessibility

UI changes should follow [ACCESSIBILITY.md](ACCESSIBILITY.md). Before submitting:

- Keyboard-only pass on affected flows
- Visible focus states
- Form labels and readable error messages
- Screen reader spot-check (VoiceOver on macOS or NVDA on Windows)

Report accessibility bugs using the [accessibility issue template](https://github.com/iamsaurabhc/picard-oss/issues/new?template=accessibility.yml).

## Security

Do **not** open public issues for security vulnerabilities. See [SECURITY.md](SECURITY.md) for responsible disclosure.

## Getting help

- **Bug reports:** [GitHub Issues](https://github.com/iamsaurabhc/picard-oss/issues)
- **Feature ideas:** use the feature request template
- **Retrieval regressions:** use the retrieval regression template and include query text or gold ID when known
- **Security:** saurabh.c@picard.law (private)

We appreciate thoughtful contributions — especially those that improve citation accuracy, eval coverage, and verification UX for legal workflows.
