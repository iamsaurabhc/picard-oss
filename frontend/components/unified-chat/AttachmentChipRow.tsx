"use client";

import { FileText, X } from "lucide-react";
import type { AttachedDocument } from "@/lib/unifiedChatTypes";
import { cn } from "@/lib/utils";

function statusLabel(status: AttachedDocument["status"]): string {
  switch (status) {
    case "ready":
      return "Ready";
    case "error":
      return "Error";
    case "parsing":
      return "Parsing…";
    case "indexing":
      return "Indexing…";
    default:
      return "Pending…";
  }
}

function statusColor(status: AttachedDocument["status"]): string {
  switch (status) {
    case "ready":
      return "bg-[var(--status-ready)]";
    case "error":
      return "bg-[var(--status-error)]";
    case "parsing":
    case "indexing":
      return "bg-[var(--status-indexing)] animate-pulse";
    default:
      return "bg-[var(--status-pending)]";
  }
}

type Props = {
  attachments: AttachedDocument[];
  onRemove: (id: string) => void;
};

export function AttachmentChipRow({ attachments, onRemove }: Props) {
  if (attachments.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-1.5 px-3 pt-3">
      {attachments.map((a) => (
        <span
          key={a.id}
          className={cn("attachment-chip", a.status === "error" && "border-red-200 bg-red-50")}
          title={a.error}
        >
          <FileText className="h-3 w-3 shrink-0 text-neutral-500" />
          <span className="max-w-[120px] truncate">{a.fileName}</span>
          <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", statusColor(a.status))} />
          <span className="text-neutral-500">{statusLabel(a.status)}</span>
          <button
            type="button"
            className="text-neutral-400 hover:text-neutral-700"
            onClick={() => onRemove(a.id)}
            aria-label={`Remove ${a.fileName}`}
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
    </div>
  );
}
