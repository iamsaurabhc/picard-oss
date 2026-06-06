# Picard API → Agent tool map (UC-04)

Phase 7a exposes workspace operations as LightAgent tools. Settings, secrets, and raw file bytes are **not** agent tools.

## Mapped tools

| API area | Agent tool |
| -------- | ----------- |
| `GET /workspaces/{id}/documents` | `list_documents` |
| `POST /workspaces/{id}/documents` | `upload_documents` (UI hint) |
| Parse jobs | `wait_parse_job` |
| Session scope | `set_session_scope` |
| `POST /search` | `search_corpus` |
| `POST /chat/stream` (rag) | `answer_from_corpus` (same kernel) |
| Chunks | `read_chunks` |
| Tabular list/read | `list_tabular_reviews`, `read_tabular_cells` |
| Workflows CRUD | `list_workflows`, `read_workflow`, `validate_flow`, `propose_flow`, `save_flow` |

## Explicit exclusions

| API | Reason |
| --- | ------ |
| `PUT /settings`, `/settings/secrets` | Admin-only; no agent mutation |
| `POST /workflows/{id}/run` | Phase 7b — `run_workflow` returns error |
| `POST /tabular/...` batch extract | Phase 7b — `run_tabular_extract` deferred |
| Connectors, web fetch | Phase 9 |
| CSV ingest, templates | Phase 8 |
| `DELETE /documents` | Destructive; not in 7a registry |

## Phase 7b

- `run_workflow` → `picard_flow_runner` + LightFlow
- `POST /workflows/{id}/run` SSE trace
