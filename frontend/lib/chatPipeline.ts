import { publishDocxSuggestion } from "@/lib/docxSuggestionStore";
import { picardApi, type ChatStreamEvent, type DocxSuggestion } from "@/lib/picardApi";
import { TABULAR_TEMPLATES } from "@/lib/tabular/columnPresets";
import type { AttachedDocument, PipelineEvent, SendParams } from "@/lib/unifiedChatTypes";
import { mergeDocumentScope } from "@/lib/unifiedChatTypes";

const INDEX_TIMEOUT_MS = 5 * 60 * 1000;
const POLL_MS = 1000;

async function waitForAttachmentsReady(
  attachments: AttachedDocument[],
  onProgress: (ready: number, total: number) => void
): Promise<void> {
  const active = attachments.filter((a) => a.status !== "error");
  if (active.length === 0) return;

  const deadline = Date.now() + INDEX_TIMEOUT_MS;

  while (Date.now() < deadline) {
    let ready = 0;
    for (const att of active) {
      if (att.status === "ready") {
        ready += 1;
        continue;
      }
      const doc = await picardApi.getDocument(att.id);
      if (doc.parse_status === "done") {
        att.status = "ready";
        ready += 1;
      } else if (doc.parse_status === "error") {
        att.status = "error";
        att.error = doc.parse_error ?? "Parse failed";
        throw new Error(`Failed to index ${att.fileName}: ${att.error}`);
      } else if (doc.parse_status === "parsing") {
        att.status = "parsing";
      } else {
        att.status = "pending";
      }
    }
    onProgress(ready, active.length);
    if (ready >= active.length) return;
    await new Promise((r) => setTimeout(r, POLL_MS));
  }
  throw new Error("Document indexing timed out. Try again in a moment.");
}

export async function* executeSend(
  params: SendParams,
  onStreamEvent?: (ev: ChatStreamEvent) => void
): AsyncGenerator<PipelineEvent> {
  const activeAttachments = params.attachments.filter((a) => a.status !== "error");

  if (activeAttachments.some((a) => a.status !== "ready")) {
    try {
      await waitForAttachmentsReady(activeAttachments, (ready, total) => {
        /* progress via polling in container */
      });
    } catch (e) {
      yield { type: "error", detail: e instanceof Error ? e.message : "Indexing failed" };
      return;
    }
  }

  const scopeIds = mergeDocumentScope(params.documentIds, activeAttachments);

  if (params.mode === "review") {
    const template =
      TABULAR_TEMPLATES.find((t) => t.id === params.templateId) ?? TABULAR_TEMPLATES[0];
    if (scopeIds.length === 0) {
      yield { type: "error", detail: "Select at least one document for a tabular review." };
      return;
    }
    const title = params.message.trim() || template.defaultTitle;
    try {
      const review = await picardApi.createTabularReview({
        workspace_id: params.workspaceId,
        title,
        columns: template.columns,
        document_ids: scopeIds,
      });
      yield {
        type: "tabular_preview",
        reviewId: review.id,
        title: review.title,
        columnCount: review.columns.length,
      };
    } catch (e) {
      yield { type: "error", detail: e instanceof Error ? e.message : "Failed to create review" };
    }
    return;
  }

  let assistant = "";
  let refs: import("@/lib/picardApi").ChatReference[] = [];
  let refused = false;
  let suggestions: string[] = [];

  try {
    for await (const ev of picardApi.streamChat({
      session_id: params.sessionId,
      workspace_id: params.workspaceId,
      message: params.message,
      document_ids: scopeIds.length ? scopeIds : undefined,
    })) {
      onStreamEvent?.(ev);
      if (ev.event === "error") {
        const msg = ("detail" in ev && ev.detail) || ("message" in ev && ev.message) || "Error";
        yield { type: "error", detail: String(msg) };
        return;
      }
      if (ev.event === "content" && "delta" in ev) {
        assistant += ev.delta;
        yield { type: "assistant_delta", delta: ev.delta };
      } else if (ev.event === "docx_suggestion") {
        const suggestion: DocxSuggestion = {
          document_id: ev.document_id,
          find: ev.find,
          replace: ev.replace,
          change_mode: ev.change_mode,
          rationale: ev.rationale,
        };
        publishDocxSuggestion(suggestion);
        yield { type: "docx_suggestion", suggestion };
      } else if (ev.event === "references") {
        refs = ev.references ?? [];
        if (typeof ev.content === "string" && ev.content.length > 0) assistant = ev.content;
        refused = !!ev.refused;
        suggestions = ev.suggestions ?? [];
      }
    }
    yield {
      type: "assistant_done",
      content: assistant,
      references: refused ? undefined : refs,
      refused,
      suggestions: refused ? suggestions : undefined,
    };
  } catch (e) {
    yield { type: "error", detail: e instanceof Error ? e.message : "Chat stream failed" };
  }
}

export function upsertStreamingAssistant(
  messages: import("@/lib/unifiedChatTypes").UnifiedMessage[],
  content: string,
  extras?: Partial<{
    references: import("@/lib/picardApi").ChatReference[];
    refused: boolean;
    suggestions: string[];
  }>
): import("@/lib/unifiedChatTypes").UnifiedMessage[] {
  const copy = [...messages];
  const last = copy[copy.length - 1];
  const msg = { type: "assistant_qa" as const, content, ...extras };
  if (last?.type === "assistant_qa" && !last.id) {
    copy[copy.length - 1] = { ...last, ...msg };
  } else {
    copy.push(msg);
  }
  return copy;
}
