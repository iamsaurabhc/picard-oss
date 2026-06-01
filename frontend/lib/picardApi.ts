const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Workspace = {
  id: string;
  name: string;
  matter_ref: string | null;
  created_at: string;
  updated_at: string;
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
};

export type ChatStreamEvent =
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
};
