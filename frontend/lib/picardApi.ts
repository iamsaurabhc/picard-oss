const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

export type OcrHealth = {
  configured: boolean;
  server_url: string | null;
  reachable: boolean;
  engine: string;
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
};

export type ChatSession = {
  id: string;
  workspace_id: string | null;
  title: string | null;
  created_at: string;
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
  document_ids?: string[];
  retrieval_mode?: "auto" | "simple" | "multi_constraint";
  allow_partial_disclosure?: boolean;
  top_k?: number;
  tabular_review_id?: string;
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

export type ChatProgressPhase = "understanding" | "search" | "rank" | "generate";
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
      documents_discovered?: number;
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
  | { event: "references"; references: ChatReference[]; refused?: boolean; suggestions?: string[] }
  | { event: "done" }
  | { event: "error"; detail: string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
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
  createChatSession: (body: { workspace_id: string; title?: string }) =>
    request<ChatSession>("/chat/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  listChatMessages: (sessionId: string) =>
    request<ChatMessage[]>(`/chat/sessions/${sessionId}/messages`),
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
};
