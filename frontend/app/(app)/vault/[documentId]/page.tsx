"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { LayoutInspectorPanel } from "@/components/LayoutInspectorPanel";
import { PdfToDocxDialog } from "@/components/docx/PdfToDocxDialog";
import { DocxViewerDynamic } from "@/components/docx/DocxViewerDynamic";
import { isDocxDocument } from "@/components/DocumentViewerRouter";
import { LayoutPDFViewer } from "@/components/pdf/PdfViewerDynamic";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/badge";
import { documentTypeLabel } from "@/lib/documentTypes";
import { picardApi } from "@/lib/picardApi";

export default function VaultDocumentPage() {
  const params = useParams<{ documentId: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const documentId = params.documentId;
  const [page, setPage] = useState(1);
  const [selectedChunkId, setSelectedChunkId] = useState<string | null>(null);
  const [showAllBlocks, setShowAllBlocks] = useState(true);
  const [showConvert, setShowConvert] = useState(false);

  const { data: document, isLoading: docLoading } = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => picardApi.getDocument(documentId),
    refetchInterval: (q) => {
      const status = q.state.data?.parse_status;
      return status === "pending" || status === "parsing" ? 2000 : false;
    },
  });

  const isDocx = document ? isDocxDocument(document) : false;

  const { data: allChunks = [], isLoading: chunksLoading } = useQuery({
    queryKey: ["document-chunks", documentId, "all"],
    queryFn: () => picardApi.getDocumentChunks(documentId),
    enabled: document?.parse_status === "done" && !isDocx,
  });

  const saveDocx = useMutation({
    mutationFn: async (buffer: ArrayBuffer) => {
      const blob = new Blob([buffer], {
        type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      });
      const file = new File([blob], document?.file_name ?? "document.docx", {
        type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      });
      return picardApi.updateDocumentFile(documentId, file);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["document", documentId] });
      void queryClient.invalidateQueries({ queryKey: ["document-chunks", documentId] });
    },
  });

  const pageChunks = useMemo(
    () => allChunks.filter((c) => c.page_number === page),
    [allChunks, page]
  );

  useEffect(() => {
    if (pageChunks.length > 0 && selectedChunkId && !pageChunks.some((c) => c.id === selectedChunkId)) {
      setSelectedChunkId(null);
    }
  }, [pageChunks, selectedChunkId]);

  if (docLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-neutral-500">
        Loading document…
      </div>
    );
  }

  if (!document) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 text-sm text-neutral-500">
        <p>Document not found.</p>
        <Link href="/vault" className="text-neutral-900 underline">
          Back to Vault
        </Link>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 items-center gap-2 border-b border-neutral-200 bg-white px-4 py-2 text-sm">
        <Link href="/vault" className="text-neutral-500 hover:text-neutral-900">
          Vault
        </Link>
        <span className="text-neutral-300">/</span>
        <span className="truncate font-medium text-neutral-900">{document.file_name}</span>
        <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-xs text-neutral-600">
          {documentTypeLabel(document.file_type)}
        </span>
        <StatusBadge status={document.parse_status} />
        {!isDocx && document.parse_status === "done" ? (
          <Button size="sm" variant="outline" className="ml-auto" onClick={() => setShowConvert(true)}>
            Convert to Word
          </Button>
        ) : null}
      </header>

      <div className="flex min-h-0 flex-1">
        {isDocx ? (
          <div className="flex h-full min-h-0 w-full min-w-0 flex-1 flex-col">
            <DocxViewerDynamic
              documentId={documentId}
              fileName={document.file_name}
              onSave={async (buffer) => {
                await saveDocx.mutateAsync(buffer);
              }}
              saving={saveDocx.isPending}
            />
          </div>
        ) : (
          <>
            <div className="min-w-0 flex-[55]">
              <LayoutPDFViewer
                documentId={documentId}
                page={page}
                onPageChange={setPage}
                chunks={allChunks}
                selectedChunkId={selectedChunkId}
                showAllBlocks={showAllBlocks}
              />
            </div>
            <div className="min-w-0 flex-[45]">
              {chunksLoading && document.parse_status === "done" ? (
                <div className="flex h-full items-center justify-center border-l border-neutral-200 text-sm text-neutral-500">
                  Loading layout…
                </div>
              ) : (
                <LayoutInspectorPanel
                  document={document}
                  page={page}
                  chunks={pageChunks}
                  selectedChunkId={selectedChunkId}
                  onSelectChunk={(id) => {
                    const chunk = allChunks.find((c) => c.id === id);
                    if (chunk) {
                      setPage(chunk.page_number);
                      setSelectedChunkId(id);
                      setShowAllBlocks(false);
                    }
                  }}
                  showAllBlocks={showAllBlocks}
                  onShowAllBlocksChange={setShowAllBlocks}
                />
              )}
            </div>
          </>
        )}
      </div>

      {showConvert ? (
        <PdfToDocxDialog
          document={document}
          onClose={() => setShowConvert(false)}
          onConverted={(newId) => router.push(`/vault/${newId}`)}
        />
      ) : null}
    </div>
  );
}
