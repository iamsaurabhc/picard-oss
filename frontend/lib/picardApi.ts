const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

const REQUEST_TIMEOUT_MS = 15_000;
/** Pip + spaCy model download can exceed the default API timeout. */
const COMPONENT_INSTALL_TIMEOUT_MS = 30 * 60 * 1000;

export function documentFileUrl(documentId: string): string {
  return `${API_URL}/documents/${documentId}/file`;
}

export type Workspace = {
  id: string;
  name: string;
  matter_ref: string | null;
  created_at: string;
  updated_at: string;
};

export type WorkspaceDocumentCounts = {
  total: number;
  done: number;
  pending: number;
  parsing: number;
  error: number;
};

export type PartyHighlight = {
  display_value: string;
  document_count: number;
};

export type DocTypeCount = {
  doc_type: string;
  count: number;
};

export type WorkspaceOverview = {
  workspace: Workspace;
  documents: WorkspaceDocumentCounts;
  tabular_reviews: number;
  parties: PartyHighlight[];
  doc_types: DocTypeCount[];
  recent_documents: DocumentRecord[];
};

export type DocumentRecord = {
  id: string;
  workspace_id: string;
  file_name: string;
  content_hash: string | null;
  page_count: number | null;
  parse_status: string;
  parse_error: string | null;
  text_source: string | null;
  ocr_engine: string | null;
  created_at: string;
};

export type ChunkRecord = {
  id: string;
  document_id: string;
  page_number: number;
  chunk_type: "heading" | "paragraph" | "table" | "list";
  bbox: Record<string, number>;
  text_content: string;
  heading_path: string | null;
  section_key: string | null;
  token_count: number | null;
};

export type AppSettings = {
  llm_provider: string;
  llm_model: string;
  ollama_base_url: string;
  enable_tiered_models: boolean;
  slm_model: string | null;
  enable_llm_query_understanding: boolean;
  enable_query_expansion: boolean;
  enable_context_ranker: boolean;
  enable_excerpt_selector: boolean;
  enable_carp: boolean;
  chat_latency_profile: string;
  enable_pii_protection_default: boolean;
  pii_protection_available: boolean;
  enable_ner_entity_extract: boolean;
  enable_slm_entity_extract: boolean;
  liteparse_ocr_server_url: string | null;
  picard_data_dir: string;
  onboarding_complete: boolean;
  show_prompts_in_chat: boolean;
  agent_profile: string;
  enable_agent_mode: boolean;
  chat_mode_default: string;
  agent_max_iterations: number;
  agent_scope_confirm_min_docs: number;
  agent_skip_scope_hitl: boolean;
  mem0_store_on_run_end: boolean;
  mem0_max_entries: number;
  agent_pack_installed: boolean;
  agent_pack_error: string | null;
  update_channel: string;
  release_manifest_url: string;
  llm_configured: boolean;
  openai_api_key_set: boolean;
  anthropic_api_key_set: boolean;
  version: string;
};

export type AppSettingsUpdate = {
  llm_provider?: string;
  llm_model?: string;
  ollama_base_url?: string;
  enable_tiered_models?: boolean;
  slm_model?: string | null;
  enable_llm_query_understanding?: boolean;
  enable_query_expansion?: boolean;
  enable_context_ranker?: boolean;
  enable_excerpt_selector?: boolean;
  enable_carp?: boolean;
  chat_latency_profile?: string;
  enable_pii_protection_default?: boolean;
  enable_ner_entity_extract?: boolean;
  enable_slm_entity_extract?: boolean;
  liteparse_ocr_server_url?: string | null;
  onboarding_complete?: boolean;
  show_prompts_in_chat?: boolean;
  agent_profile?: string;
  enable_agent_mode?: boolean;
  chat_mode_default?: string;
  agent_max_iterations?: number;
  agent_scope_confirm_min_docs?: number;
  agent_skip_scope_hitl?: boolean;
  mem0_store_on_run_end?: boolean;
  mem0_max_entries?: number;
  update_channel?: string;
};

export type AgentRun = {
  id: string;
  session_id: string | null;
  workspace_id: string;
  profile: string;
  mode: string;
  plan_json: Record<string, unknown> | null;
  events: Record<string, unknown>[];
  status: string;
  created_at: string;
  updated_at: string;
};

export type WorkflowType = "assistant" | "tabular" | "lightflow";
export type WorkflowProfile = "firm" | "court" | "any";

export type WorkflowRecord = {
  id: string;
  workspace_id: string | null;
  type: WorkflowType;
  title: string;
  practice_area: string | null;
  prompt_md: string | null;
  columns_config: TabularColumn[] | null;
  flow_json: {
    version: string;
    input_hint?: string;
    steps: Array<{
      name: string;
      role: string;
      depends_on?: string[];
      refuse_on_empty?: boolean;
      config?: Record<string, unknown>;
    }>;
  };
  flow_version: string;
  input_schema: Record<string, unknown> | null;
  evidence_profile: {
    requires_corpus?: boolean;
    allowed_intents?: string[];
    allows_tabular?: boolean;
    allows_csv?: boolean;
    allows_web?: boolean;
    denied_roles?: string[];
  };
  profile: WorkflowProfile;
  source: string;
  requires_approval: boolean;
  is_builtin: boolean;
  created_at: string;
  updated_at: string;
};

export type WorkflowValidation = {
  valid: boolean;
  errors: Array<{ level: string; code: string; message: string; step?: string | null }>;
  warnings: Array<{ level: string; code: string; message: string; step?: string | null }>;
};

export type AppComponent = {
  id: string;
  name: string;
  description: string;
  installed: boolean;
  running: boolean;
  optional: boolean;
  install_hint?: string;
  ml_deps_installed?: boolean;
};

export type UpdateCheck = {
  current_version: string;
  latest_version: string;
  update_available: boolean;
  download_url: string | null;
  notes_url: string | null;
  channel: string;
};

export type PromptSummary = {
  key: string;
  is_overridden: boolean;
  preview: string;
  length: number;
};

export type PromptDetail = {
  key: string;
  text: string;
  is_overridden: boolean;
  default_preview: string;
};

export type OcrHealth = {
  configured: boolean;
  server_url: string | null;
  reachable: boolean;
  engine: string;
  tesseract_ready?: boolean;
};

export type SearchHit = {
  chunk_id: string;
  document_id: string;
  page_number: number;
  text_content: string;
  heading_path: string | null;
  section_key?: string | null;
  bbox?: Record<string, number> | null;
  score: number;
};

export type ContextBundle = {
  bundle_id: string;
  document_id: string;
  page_start: number;
  page_end: number;
  section_key: string | null;
  heading_path: string | null;
  chunk_ids: string[];
  constraints_matched: string[];
  constraints_missing: string[];
  proximity_tier: string;
  bm25_score: number;
  coherence_score: number;
  score: number;
};

export type SearchResponse = {
  mode: "SIMPLE" | "MULTI_CONSTRAINT";
  hits: SearchHit[];
  bundles?: ContextBundle[] | null;
  retrieval_diagnostics?: Record<string, unknown> | null;
  proximity_tier_used?: string | null;
  refused: boolean;
  expanded_query?: string | null;
  suggestions?: string[];
};

export type SearchRequest = {
  query: string;
  workspace_id: string;
  top_k?: number;
  document_ids?: string[];
  metadata_filters?: Record<string, string>;
  retrieval_mode?: "auto" | "simple" | "multi_constraint";
  proximity_max_tier?: string;
  allow_partial_disclosure?: boolean;
  min_score?: number;
};

export type ChatReference = {
  index: number;
  chunk_id: string;
  document_id: string;
  page: number;
  bbox?: Record<string, number> | null;
  preview: string;
  bundle_id?: string | null;
  document_name?: string | null;
  heading_path?: string | null;
  pinpoint_quote?: string | null;
  highlight_bboxes?: Record<string, number>[] | null;
  sentence_anchors?: Array<{
    sentence: string;
    chunk_id: string;
    bbox?: Record<string, number> | null;
    score?: number;
  }> | null;
  page_chunks?: Array<{
    chunk_id: string;
    text: string;
    bbox?: Record<string, number> | null;
  }> | null;
  document_binding_chunks?: Array<{
    chunk_id: string;
    text: string;
    bbox?: Record<string, number> | null;
    page?: number;
  }> | null;
};

export type ChatSessionSummary = {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
  has_user_message: boolean;
  preview: string | null;
};

export type ChatSession = {
  id: string;
  workspace_id: string | null;
  title: string | null;
  created_at: string;
  updated_at: string;
  document_ids: string[];
};

export type ChatMessage = {
  id: string;
  session_id: string;
  role: string;
  content: string;
  references?: ChatReference[] | null;
  refused: boolean;
  created_at: string;
};

export type ChatStreamRequest = {
  session_id: string;
  workspace_id: string;
  message: string;
  mode?: "rag" | "agent";
  approval_token?: string;
  document_ids?: string[];
  retrieval_mode?: "auto" | "simple" | "multi_constraint";
  allow_partial_disclosure?: boolean;
  top_k?: number;
  tabular_review_id?: string;
  workflow_id?: string;
  enable_pii_protection?: boolean;
};

export type ColumnFormat =
  | "text"
  | "bulleted_list"
  | "number"
  | "currency"
  | "yes_no"
  | "date"
  | "tag"
  | "percentage"
  | "monetary_amount";

export type TabularColumn = {
  key: string;
  label: string;
  format: ColumnFormat;
  prompt: string;
  tag_options?: string[];
};

export type TabularCell = {
  id: string;
  review_id: string;
  document_id: string;
  column_key: string;
  summary: string | null;
  reasoning: string | null;
  flag: "green" | "grey" | "yellow" | "red" | null;
  status: "pending" | "generating" | "done" | "error";
  source_chunk_ids: string[];
};

export type TabularReviewSummary = {
  id: string;
  workspace_id: string;
  title: string;
  column_count: number;
  document_count: number;
  created_at: string;
};

export type TabularReview = {
  id: string;
  workspace_id: string;
  title: string;
  columns: TabularColumn[];
  document_ids: string[];
  documents: DocumentRecord[];
  cells: TabularCell[];
  created_at: string;
};

export type TabularStreamEvent =
  | { event: "batch_start"; review_id: string; total_cells: number }
  | { event: "cell_start"; cell_id: string; document_id: string; column_key: string }
  | { event: "cell_done"; cell: TabularCell }
  | { event: "cell_error"; cell_id: string; error: string }
  | { event: "batch_complete"; review_id: string; done: number; errors: number }
  | { event: "error"; detail: string };

export type ChatProgressPhase =
  | "understanding"
  | "search"
  | "page_rank"
  | "coverage"
  | "context"
  | "map"
  | "reduce"
  | "rank"
  | "generate";
export type ChatProgressStatus = "start" | "done";

export type ChatStreamEvent =
  | {
      event: "progress";
      phase: ChatProgressPhase;
      status: ChatProgressStatus;
      intent?: string;
      mode?: string;
      pass_count?: number;
      used_llm?: boolean;
      label?: string;
      strategy?: string;
      hit_count?: number;
      ranked_count?: number;
      constraint_count?: number;
      intersection_pages?: number;
      document_name?: string;
      document_id?: string;
      documents_discovered?: number;
      documents_to_map?: number;
      brief_count?: number;
      chunk_count?: number;
      pages_selected?: number[];
      target_entity?: string;
      [key: string]: unknown;
    }
  | {
      event: "snippet";
      chunk_id: string;
      document_id: string;
      document_name: string;
      page_number: number;
      text: string;
      source: string;
      score?: number;
    }
  | { event: "retrieval"; chunk_count: number; bundle_count: number; refused: boolean; mode: string; diagnostics?: Record<string, unknown> }
  | { event: "content"; delta: string }
  | {
      event: "references";
      references: ChatReference[];
      content?: string;
      refused?: boolean;
      suggestions?: string[];
    }
  | { event: "done" }
  | { event: "error"; detail?: string; message?: string }
  | { event: "memory_hit"; memories: string[] }
  | { event: "plan"; plan?: string }
  | {
      event: "approval_required";
      kind: "scope" | "plan";
      token: string;
      document_count?: number;
      document_ids?: string[];
      flow_json?: WorkflowRecord["flow_json"];
    }
  | { event: "tool_call"; tool?: string; arguments?: unknown }
  | { event: "tool_result"; tool?: string; output?: unknown }
  | { event: "workflow_draft"; flow_json: WorkflowRecord["flow_json"]; goal?: string }
  | { event: "workflow_applied"; workflow_id: string; title?: string }
  | { event: "step_refused"; tool?: string; query?: string };

type RequestOptions = {
  timeoutMs?: number;
};

async function request<T>(path: string, init?: RequestInit, options?: RequestOptions): Promise<T> {
  const timeoutMs = options?.timeoutMs ?? REQUEST_TIMEOUT_MS;
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    signal: init?.signal ?? AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) {
    const text = await res.text();
    let message = text || res.statusText;
    try {
      const parsed = JSON.parse(text) as { detail?: string };
      if (typeof parsed.detail === "string") message = parsed.detail;
    } catch {
      /* keep raw body */
    }
    throw new Error(message);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export type DocumentStatusEvent =
  | { event: "status"; document_id: string; parse_status: string; progress?: number; parse_error?: string }
  | { event: "indexing"; document_id: string; phase: string }
  | { event: "ready"; document_id: string; chunk_count: number; page_count: number }
  | { event: "error"; detail: string };

function parseGenericSseBlock(block: string): DocumentStatusEvent | null {
  let eventType = "message";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) eventType = line.slice(6).trim();
    else if (line.startsWith("data:")) data = line.slice(5).trim();
  }
  if (!data) return null;
  try {
    const parsed = JSON.parse(data) as Record<string, unknown>;
    return { event: eventType, ...parsed } as DocumentStatusEvent;
  } catch {
    return null;
  }
}

async function* parseGenericSseStream(
  reader: ReadableStreamDefaultReader<Uint8Array>
): AsyncGenerator<DocumentStatusEvent> {
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (value) {
      buffer += decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n");
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() ?? "";
      for (const block of blocks) {
        const ev = parseGenericSseBlock(block);
        if (ev) yield ev;
      }
    }
    if (done) {
      buffer += decoder.decode(undefined, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n");
      for (const block of buffer.split("\n\n")) {
        const ev = parseGenericSseBlock(block);
        if (ev) yield ev;
      }
      break;
    }
  }
}

function parseSseBlock(block: string): ChatStreamEvent | null {
  let eventType = "message";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) eventType = line.slice(6).trim();
    else if (line.startsWith("data:")) data = line.slice(5).trim();
  }
  if (!data) return null;
  try {
    const parsed = JSON.parse(data) as Record<string, unknown>;
    return { event: eventType, ...parsed } as ChatStreamEvent;
  } catch {
    return null;
  }
}

async function* parseSseStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  onEvent?: (ev: ChatStreamEvent) => void
): AsyncGenerator<ChatStreamEvent> {
  const decoder = new TextDecoder();
  let buffer = "";

  const flushBlocks = function* (final = false) {
    buffer = buffer.replace(/\r\n/g, "\n");
    const blocks = buffer.split("\n\n");
    buffer = final ? "" : (blocks.pop() ?? "");
    for (const block of blocks) {
      const ev = parseSseBlock(block);
      if (!ev) continue;
      onEvent?.(ev);
      yield ev;
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (value) {
      buffer += decoder.decode(value, { stream: true });
      yield* flushBlocks(false);
    }
    if (done) {
      buffer += decoder.decode(undefined, { stream: true });
      yield* flushBlocks(true);
      break;
    }
  }
}

export const picardApi = {
  listWorkspaces: () => request<Workspace[]>("/workspaces"),
  createWorkspace: (body: { name: string; matter_ref?: string }) =>
    request<Workspace>("/workspaces", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getWorkspace: (id: string) => request<Workspace>(`/workspaces/${id}`),
  getWorkspaceOverview: (id: string) => request<WorkspaceOverview>(`/workspaces/${id}/overview`),
  listDocuments: (workspaceId: string) =>
    request<DocumentRecord[]>(`/workspaces/${workspaceId}/documents`),
  uploadDocument: async (workspaceId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<DocumentRecord>(`/workspaces/${workspaceId}/documents`, {
      method: "POST",
      body: form,
    });
  },
  getDocument: (id: string) => request<DocumentRecord>(`/documents/${id}`),
  getDocumentChunks: (documentId: string, params?: { page?: number }) => {
    const qs = params?.page != null ? `?page=${params.page}` : "";
    return request<ChunkRecord[]>(`/documents/${documentId}/chunks${qs}`);
  },
  getOcrHealth: () => request<OcrHealth>("/health/ocr"),
  retryDocument: (id: string) =>
    request<{ job_id: string; document_id: string }>(`/documents/${id}/retry`, { method: "POST" }),
  retryAllDocuments: (workspaceId: string) =>
    request<{ retried_count: number; document_ids: string[] }>(
      `/workspaces/${workspaceId}/documents/retry-all`,
      { method: "POST" }
    ),
  search: (body: SearchRequest) =>
    request<SearchResponse>("/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  createChatSession: (body: { workspace_id: string; title?: string; reuse_draft?: boolean }) =>
    request<ChatSession>("/chat/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  listChatSessions: (workspaceId: string) =>
    request<ChatSessionSummary[]>(`/workspaces/${workspaceId}/chat/sessions`),
  getChatSession: (sessionId: string) => request<ChatSession>(`/chat/sessions/${sessionId}`),
  deleteChatSession: (sessionId: string) =>
    request<void>(`/chat/sessions/${sessionId}`, { method: "DELETE" }),
  listChatMessages: (sessionId: string) =>
    request<ChatMessage[]>(`/chat/sessions/${sessionId}/messages`),
  getAgentRun: (runId: string) => request<AgentRun>(`/agent/runs/${runId}`),
  streamDocumentStatus: async function* (documentId: string): AsyncGenerator<DocumentStatusEvent> {
    const res = await fetch(`${API_URL}/documents/${documentId}/status/stream`, {
      headers: { Accept: "text/event-stream" },
    });
    if (!res.ok) throw new Error(await res.text());
    const reader = res.body?.getReader();
    if (!reader) return;
    yield* parseGenericSseStream(reader);
  },
  streamChat: async function* (
    body: ChatStreamRequest,
    onEvent?: (ev: ChatStreamEvent) => void
  ): AsyncGenerator<ChatStreamEvent> {
    const res = await fetch(`${API_URL}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await res.text());
    const reader = res.body?.getReader();
    if (!reader) return;
    yield* parseSseStream(reader, onEvent);
  },
  listTabularReviews: (workspaceId: string) =>
    request<TabularReviewSummary[]>(`/workspaces/${workspaceId}/tabular/reviews`),
  createTabularReview: (body: {
    workspace_id: string;
    title: string;
    columns: TabularColumn[];
    document_ids: string[];
  }) =>
    request<TabularReview>("/tabular/reviews", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getTabularReview: (reviewId: string) => request<TabularReview>(`/tabular/reviews/${reviewId}`),
  updateTabularReview: (
    reviewId: string,
    body: { title?: string; columns?: TabularColumn[]; document_ids?: string[] }
  ) =>
    request<TabularReview>(`/tabular/reviews/${reviewId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteTabularReview: (reviewId: string) =>
    request<void>(`/tabular/reviews/${reviewId}`, { method: "DELETE" }),
  generateColumnPrompt: (body: {
    label: string;
    format?: ColumnFormat;
    idea?: string;
  }) =>
    request<{ prompt: string; from_preset: boolean; suggested_format: ColumnFormat }>(
      "/tabular/generate-column-prompt",
      {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  regenerateTabularCell: (cellId: string) =>
    request<TabularCell>(`/tabular/cells/${cellId}/regenerate`, { method: "POST" }),
  tabularExportUrl: (reviewId: string) => `${API_URL}/tabular/reviews/${reviewId}/export.xlsx`,

  getSettings: () => request<AppSettings>("/settings"),
  updateSettings: (body: Partial<AppSettingsUpdate>) =>
    request<AppSettings>("/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  updateSecrets: (body: { openai_api_key?: string; anthropic_api_key?: string }) =>
    request<{ ok: boolean; openai_api_key_set: boolean; anthropic_api_key_set: boolean }>(
      "/settings/secrets",
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }
    ),
  resetSettings: (keepSecrets = true) =>
    request<AppSettings>("/settings/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keep_secrets: keepSecrets }),
    }),
  getOnboardingStatus: () =>
    request<{ needs_onboarding: boolean; llm_configured: boolean }>("/settings/onboarding-status"),
  getComponents: () =>
    request<{ components: AppComponent[] }>("/settings/components"),
  installComponent: (id: string) =>
    request<{ ok: boolean; message: string }>(
      `/settings/components/${id}/install`,
      { method: "POST" },
      { timeoutMs: COMPONENT_INSTALL_TIMEOUT_MS },
    ),
  checkForUpdates: () => request<UpdateCheck>("/updates/check"),
  getVersion: () => request<{ version: string; channel?: string; build_sha?: string | null }>("/version"),
  listPrompts: () => request<{ prompts: PromptSummary[] }>("/prompts"),
  getPrompt: (key: string) => request<PromptDetail>(`/prompts/${key}`),
  updatePrompt: (key: string, text: string) =>
    request<PromptDetail>(`/prompts/${key}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
  resetPrompt: (key: string) =>
    request<PromptDetail>(`/prompts/${key}`, { method: "DELETE" }),
  streamTabularGeneration: async function* (
    reviewId: string,
    body?: { document_ids?: string[]; column_keys?: string[]; only_pending?: boolean }
  ): AsyncGenerator<TabularStreamEvent> {
    const res = await fetch(`${API_URL}/tabular/reviews/${reviewId}/generate/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body ?? { only_pending: true }),
    });
    if (!res.ok) throw new Error(await res.text());
    const reader = res.body?.getReader();
    if (!reader) return;
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (value) buffer += decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, "\n");
      const blocks = buffer.split("\n\n");
      buffer = done ? "" : (blocks.pop() ?? "");
      for (const block of blocks) {
        let eventType = "message";
        let data = "";
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) eventType = line.slice(6).trim();
          else if (line.startsWith("data:")) data = line.slice(5).trim();
        }
        if (!data) continue;
        try {
          const parsed = JSON.parse(data) as Record<string, unknown>;
          yield { event: eventType, ...parsed } as TabularStreamEvent;
        } catch {
          /* skip */
        }
      }
      if (done) break;
    }
  },
  listWorkflows: (params?: {
    workspace_id?: string;
    type?: WorkflowType;
    practice_area?: string;
  }) => {
    const qs = new URLSearchParams();
    if (params?.workspace_id) qs.set("workspace_id", params.workspace_id);
    if (params?.type) qs.set("type", params.type);
    if (params?.practice_area) qs.set("practice_area", params.practice_area);
    const q = qs.toString();
    return request<WorkflowRecord[]>(`/workflows${q ? `?${q}` : ""}`);
  },
  createWorkflow: (body: {
    workspace_id: string;
    type: WorkflowType;
    title: string;
    flow_json: WorkflowRecord["flow_json"];
    evidence_profile: WorkflowRecord["evidence_profile"];
    profile?: WorkflowProfile;
    practice_area?: string;
    prompt_md?: string;
  }) =>
    request<WorkflowRecord>("/workflows", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  getWorkflow: (id: string) => request<WorkflowRecord>(`/workflows/${id}`),
  validateWorkflow: (id: string) =>
    request<WorkflowValidation>(`/workflows/${id}/validate`, { method: "POST" }),
  hideWorkflow: (id: string) =>
    request<void>(`/workflows/${id}/hide`, { method: "POST" }),
  exportWorkflow: async (id: string) => {
    const res = await fetch(`${API_URL}/workflows/${id}/export`, { method: "POST" });
    if (!res.ok) throw new Error(await res.text());
    return res.json() as Promise<WorkflowRecord>;
  },
};
