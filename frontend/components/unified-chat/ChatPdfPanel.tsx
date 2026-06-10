"use client";

import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { isDocxDocument } from "@/components/DocumentViewerRouter";
import { DocxViewerDynamic } from "@/components/docx/DocxViewerDynamic";
import { MultiHighlightPDFViewer } from "@/components/pdf/PdfViewerDynamic";
import { picardApi, type ChatReference } from "@/lib/picardApi";

type Props = {
  documentId: string;
  activeRef: ChatReference;
  highlights: ChatReference[];
  activeClaimText?: string | null;
  onClose: () => void;
};

export function ChatPdfPanel({
  documentId,
  activeRef,
  highlights,
  activeClaimText,
  onClose,
}: Props) {
  const { data: document, isLoading } = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => picardApi.getDocument(documentId),
  });

  const isDocx = document ? isDocxDocument(document) : false;

  return (
    <div className="panel-slide-in flex h-full flex-col border-l border-neutral-200 bg-white">
      <div className="flex items-center justify-between border-b border-neutral-200 px-3 py-2">
        <span className="truncate text-sm font-medium text-neutral-800">
          {activeRef.document_name ?? document?.file_name ?? "Document"}
        </span>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-1 text-neutral-500 hover:bg-neutral-100 hover:text-neutral-800"
          aria-label="Close document panel"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1">
        {isLoading ? (
          <div className="flex h-full items-center justify-center text-sm text-neutral-500">
            Loading document…
          </div>
        ) : isDocx ? (
          <DocxViewerDynamic
            documentId={documentId}
            fileName={document?.file_name}
            citationPanel
            activeCitation={activeRef}
            activeClaimText={activeClaimText}
          />
        ) : (
          <MultiHighlightPDFViewer
            documentId={documentId}
            highlights={highlights}
            activeIndex={activeRef.index ?? null}
            activeRef={activeRef}
          />
        )}
      </div>
    </div>
  );
}
