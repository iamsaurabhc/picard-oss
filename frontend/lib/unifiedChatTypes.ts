import type { ChatReference } from "@/lib/picardApi";
import type { TabularTemplateId } from "@/lib/tabular/columnPresets";

export type ComposerMode = "ask" | "review";

export type AttachmentStatus = "pending" | "parsing" | "indexing" | "ready" | "error";

export type AttachedDocument = {
  id: string;
  fileName: string;
  status: AttachmentStatus;
  error?: string;
};

export type UnifiedMessage =
  | { type: "user_text"; id?: string; content: string; attachmentNames?: string[] }
  | {
      type: "assistant_qa";
      id?: string;
      content: string;
      references?: ChatReference[];
      refused?: boolean;
      suggestions?: string[];
    }
  | {
      type: "indexing_notice";
      id?: string;
      documents: { id: string; name: string; status: string }[];
    }
  | { type: "tabular_preview"; id?: string; reviewId: string; title: string; columnCount: number }
  | { type: "error"; id?: string; detail: string; retry?: () => void };

export type PipelineEvent =
  | { type: "assistant_delta"; delta: string }
  | {
      type: "assistant_done";
      content: string;
      references?: ChatReference[];
      refused?: boolean;
      suggestions?: string[];
    }
  | { type: "tabular_preview"; reviewId: string; title: string; columnCount: number }
  | { type: "indexing"; ready: number; total: number }
  | { type: "error"; detail: string };

export type SendParams = {
  message: string;
  mode: ComposerMode;
  documentIds: string[];
  attachments: AttachedDocument[];
  templateId: TabularTemplateId;
  sessionId: string;
  workspaceId: string;
};

export function mergeDocumentScope(documentIds: string[], attachments: AttachedDocument[]): string[] {
  const ids = new Set(documentIds);
  for (const a of attachments) {
    if (a.status === "ready") ids.add(a.id);
  }
  return Array.from(ids);
}

export function attachmentsIndexing(attachments: AttachedDocument[]): boolean {
  return attachments.some((a) => a.status !== "ready" && a.status !== "error");
}

export function attachmentsReadyCount(attachments: AttachedDocument[]): { ready: number; total: number } {
  const active = attachments.filter((a) => a.status !== "error");
  return {
    ready: active.filter((a) => a.status === "ready").length,
    total: active.length,
  };
}
