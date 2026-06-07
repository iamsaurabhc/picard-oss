"use client";

import { X } from "lucide-react";
import { MultiHighlightPDFViewer } from "@/components/pdf/PdfViewerDynamic";
import type { ChatReference } from "@/lib/picardApi";

type Props = {
  documentId: string;
  activeRef: ChatReference;
  highlights: ChatReference[];
  onClose: () => void;
};

export function ChatPdfPanel({ documentId, activeRef, highlights, onClose }: Props) {
  return (
    <div className="panel-slide-in flex h-full flex-col border-l border-neutral-200 bg-white">
      <div className="flex items-center justify-between border-b border-neutral-200 px-3 py-2">
        <span className="truncate text-sm font-medium text-neutral-800">
          {activeRef.document_name ?? "Document"}
        </span>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-1 text-neutral-500 hover:bg-neutral-100 hover:text-neutral-800"
          aria-label="Close PDF panel"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1">
        <MultiHighlightPDFViewer
          documentId={documentId}
          highlights={highlights}
          activeIndex={activeRef.index ?? null}
          activeRef={activeRef}
        />
      </div>
    </div>
  );
}
