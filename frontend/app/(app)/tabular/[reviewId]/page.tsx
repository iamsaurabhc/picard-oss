"use client";

import { useCallback, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  Download,
  Loader2,
  MessageSquare,
  Play,
  Plus,
  Trash2,
} from "lucide-react";
import type { TabularCell, TabularColumn } from "@/lib/picardApi";
import { picardApi } from "@/lib/picardApi";
import { useWorkspace } from "@/lib/workspaceContext";
import { NoWorkspaceState } from "@/components/NoWorkspaceState";
import { ensureUniqueColumnKey } from "@/lib/tabular/columnPresets";
import { AddColumnModal } from "@/components/tabular/AddColumnModal";
import { AddDocumentsModal } from "@/components/tabular/AddDocumentsModal";
import { DeleteReviewDialog } from "@/components/tabular/DeleteReviewDialog";
import { TRChatPanel } from "@/components/tabular/TRChatPanel";
import { TRSidePanel } from "@/components/tabular/TRSidePanel";
import { TRTable, type TRTableHandle } from "@/components/tabular/TRTable";
import { Button } from "@/components/ui/button";

export default function TabularReviewPage() {
  const params = useParams<{ reviewId: string }>();
  const { workspaceId } = useWorkspace();
  const reviewId = params.reviewId;
  const router = useRouter();
  const searchParams = useSearchParams();
  const qc = useQueryClient();
  const tableRef = useRef<TRTableHandle>(null);

  const [addColOpen, setAddColOpen] = useState(false);
  const [addDocsOpen, setAddDocsOpen] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [expandedCell, setExpandedCell] = useState<TabularCell | null>(null);
  const [expandedCitation, setExpandedCitation] = useState<{ page: number; quote: string } | undefined>();
  const [dragOver, setDragOver] = useState(false);
  const [uploadingNames, setUploadingNames] = useState<string[]>([]);
  const [highlightedCell, setHighlightedCell] = useState<{ colIdx: number; rowIdx: number } | null>(null);
  const [chatOpen, setChatOpen] = useState(searchParams.get("chat") != null);
  const [actionsOpen, setActionsOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [addingColumn, setAddingColumn] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const { data: review, isLoading } = useQuery({
    queryKey: ["tabular-review", reviewId],
    queryFn: () => picardApi.getTabularReview(reviewId),
    enabled: !!reviewId,
    refetchInterval: generating ? 3000 : false,
  });

  const upload = useMutation({
    mutationFn: (file: File) => {
      if (!workspaceId) throw new Error("No workspace selected");
      return picardApi.uploadDocument(workspaceId, file);
    },
    onSuccess: async (doc) => {
      if (!review) return;
      const ids = [...review.document_ids, doc.id];
      await picardApi.updateTabularReview(reviewId, { document_ids: ids });
      qc.invalidateQueries({ queryKey: ["tabular-review", reviewId] });
    },
  });

  const syncChatUrl = useCallback(
    (open: boolean) => {
      const url = new URL(window.location.href);
      if (open) url.searchParams.set("chat", "open");
      else url.searchParams.delete("chat");
      router.replace(url.pathname + url.search, { scroll: false });
    },
    [router]
  );

  async function runBatchStream(opts?: { column_keys?: string[] }) {
    if (!review) return;
    setGenerating(true);
    try {
      const docFilter =
        selectedDocIds.length > 0 && selectedDocIds.length < review.documents.length
          ? selectedDocIds
          : undefined;
      for await (const ev of picardApi.streamTabularGeneration(reviewId, {
        document_ids: docFilter,
        column_keys: opts?.column_keys,
        only_pending: true,
      })) {
        if (ev.event === "cell_done" && "cell" in ev) {
          qc.setQueryData<typeof review>(["tabular-review", reviewId], (old) => {
            if (!old) return old;
            const cells = old.cells.map((c) => (c.id === ev.cell.id ? ev.cell : c));
            if (!cells.some((c) => c.id === ev.cell.id)) cells.push(ev.cell);
            return { ...old, cells };
          });
        }
      }
      await qc.invalidateQueries({ queryKey: ["tabular-review", reviewId] });
    } finally {
      setGenerating(false);
    }
  }

  async function runBatch() {
    await runBatchStream();
  }

  async function handleExportExcel() {
    setExporting(true);
    setActionsOpen(false);
    try {
      const res = await fetch(`/api/tabular/${reviewId}/export`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(typeof err.detail === "string" ? err.detail : "Export failed");
      }
      const blob = await res.blob();
      const disposition = res.headers.get("Content-Disposition") ?? "";
      const match = disposition.match(/filename="?([^";\n]+)"?/i);
      const filename = match?.[1]?.trim() || `${review?.title || "tabular-review"}.xlsx`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Export failed");
    } finally {
      setExporting(false);
    }
  }

  async function handleAddColumn(col: TabularColumn) {
    if (!review) return;
    setAddingColumn(true);
    try {
      const key = ensureUniqueColumnKey(
        col.key,
        review.columns.map((c) => c.key)
      );
      const column: TabularColumn = { ...col, key };
      const columns = [...review.columns, column];
      const updated = await picardApi.updateTabularReview(reviewId, { columns });
      qc.setQueryData(["tabular-review", reviewId], updated);
      setAddColOpen(false);
      await runBatchStream({ column_keys: [key] });
    } finally {
      setAddingColumn(false);
    }
  }

  async function confirmDeleteReview() {
    if (!workspaceId) return;
    setDeleting(true);
    try {
      await picardApi.deleteTabularReview(reviewId);
      await qc.invalidateQueries({ queryKey: ["tabular-reviews", workspaceId] });
      router.push("/tabular");
    } finally {
      setDeleting(false);
      setDeleteOpen(false);
    }
  }

  async function handleDropFiles(files: FileList) {
    const pdfs = Array.from(files).filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    for (const file of pdfs) {
      setUploadingNames((n) => [...n, file.name]);
      try {
        await upload.mutateAsync(file);
      } finally {
        setUploadingNames((n) => n.filter((x) => x !== file.name));
      }
    }
  }

  function openCell(cell: TabularCell, citation?: { page: number; quote: string }) {
    setExpandedCell(cell);
    setExpandedCitation(citation);
  }

  function scrollToCellRef(columnKey: string, documentId: string) {
    if (!review) return;
    const rowIdx = review.documents.findIndex((d) => d.id === documentId);
    const colIdx = review.columns.findIndex((c) => c.key === columnKey);
    if (rowIdx >= 0 && colIdx >= 0) {
      setHighlightedCell({ colIdx, rowIdx });
      tableRef.current?.scrollToCell(colIdx, rowIdx);
    }
  }

  const expandedDoc = expandedCell
    ? review?.documents.find((d) => d.id === expandedCell.document_id)
    : undefined;
  const expandedCol = expandedCell
    ? review?.columns.find((c) => c.key === expandedCell.column_key)
    : undefined;

  if (!workspaceId) {
    return (
      <div className="flex h-screen items-center justify-center p-8">
        <NoWorkspaceState title="Select a workspace" />
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col bg-white">
      <header className="flex shrink-0 items-center gap-3 border-b border-neutral-200 px-4 py-3">
        <Link href="/tabular" className="text-sm text-neutral-500 hover:text-neutral-900">
          ← Reviews
        </Link>
        <h1 className="min-w-0 flex-1 truncate font-serif text-lg">{review?.title ?? "…"}</h1>
        <div className="relative">
          <Button variant="outline" size="sm" onClick={() => setActionsOpen((o) => !o)}>
            Actions
            <ChevronDown className="ml-1 h-3 w-3" />
          </Button>
          {actionsOpen ? (
            <div className="absolute right-0 top-full z-30 mt-1 w-48 rounded border border-neutral-200 bg-white py-1 shadow-lg">
              <button
                type="button"
                className="flex w-full px-3 py-2 text-left text-sm hover:bg-neutral-50"
                onClick={() => {
                  setActionsOpen(false);
                  setAddDocsOpen(true);
                }}
              >
                <Plus className="mr-2 h-4 w-4" />
                Add documents
              </button>
              <button
                type="button"
                className="flex w-full px-3 py-2 text-left text-sm hover:bg-neutral-50 disabled:opacity-50"
                disabled={exporting}
                onClick={handleExportExcel}
              >
                {exporting ? (
                  <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
                ) : (
                  <Download className="mr-2 inline h-4 w-4" />
                )}
                {exporting ? "Exporting…" : "Export Excel"}
              </button>
              <button
                type="button"
                className="flex w-full px-3 py-2 text-left text-sm text-red-700 hover:bg-red-50"
                onClick={() => {
                  setActionsOpen(false);
                  setDeleteOpen(true);
                }}
              >
                <Trash2 className="mr-2 h-4 w-4" />
                Delete review
              </button>
            </div>
          ) : null}
        </div>
        <Button
          size="sm"
          disabled={generating || !review?.documents.length}
          onClick={runBatch}
        >
          {generating ? (
            <Loader2 className="mr-1 h-4 w-4 animate-spin" />
          ) : (
            <Play className="mr-1 h-4 w-4" />
          )}
          {generating ? (addingColumn ? "Extracting column…" : "Running…") : "Run extraction"}
        </Button>
        <Button
          variant={chatOpen ? "default" : "outline"}
          size="sm"
          onClick={() => {
            const next = !chatOpen;
            setChatOpen(next);
            syncChatUrl(next);
          }}
        >
          <MessageSquare className="mr-1 h-4 w-4" />
          Chat
        </Button>
      </header>

      <div
        className="flex min-h-0 flex-1"
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          if (e.dataTransfer.files.length) handleDropFiles(e.dataTransfer.files);
        }}
      >
        <TRTable
          ref={tableRef}
          loading={isLoading}
          columns={review?.columns ?? []}
          documents={review?.documents ?? []}
          cells={review?.cells ?? []}
          selectedDocIds={
            selectedDocIds.length ? selectedDocIds : (review?.documents.map((d) => d.id) ?? [])
          }
          uploadingFilenames={uploadingNames}
          dragOverFiles={dragOver}
          highlightedCell={highlightedCell}
          onSelectionChange={setSelectedDocIds}
          onExpand={(cell) => openCell(cell)}
          onCitationClick={(cell, page, quote) => openCell(cell, { page, quote })}
          onAddColumn={() => setAddColOpen(true)}
          onAddDocuments={() => setAddDocsOpen(true)}
          onDropFiles={handleDropFiles}
        />

        {expandedCell && expandedDoc && expandedCol && review ? (
          <TRSidePanel
            cell={expandedCell}
            document={expandedDoc}
            column={expandedCol}
            columns={review.columns}
            initialCitation={expandedCitation}
            onClose={() => {
              setExpandedCell(null);
              setExpandedCitation(undefined);
            }}
            onNavigate={(columnKey) => {
              const next = review.cells.find(
                (c) => c.document_id === expandedCell.document_id && c.column_key === columnKey
              );
              if (next) {
                setExpandedCell(next);
                setExpandedCitation(undefined);
              }
            }}
            onRegenerate={async () => {
              const updated = await picardApi.regenerateTabularCell(expandedCell.id);
              setExpandedCell(updated);
              qc.invalidateQueries({ queryKey: ["tabular-review", reviewId] });
            }}
          />
        ) : null}

        {chatOpen && review ? (
          <TRChatPanel
            review={review}
            workspaceId={workspaceId}
            onClose={() => {
              setChatOpen(false);
              syncChatUrl(false);
            }}
            onCellRefClick={scrollToCellRef}
          />
        ) : null}
      </div>


      <AddColumnModal
        open={addColOpen}
        saving={addingColumn}
        onClose={() => !addingColumn && setAddColOpen(false)}
        onSave={handleAddColumn}
      />

      <DeleteReviewDialog
        open={deleteOpen}
        title={review?.title ?? ""}
        deleting={deleting}
        onClose={() => setDeleteOpen(false)}
        onConfirm={confirmDeleteReview}
      />

      {review ? (
        <AddDocumentsModal
          open={addDocsOpen}
          workspaceId={workspaceId}
          reviewId={reviewId}
          existingDocIds={review.document_ids}
          onClose={() => setAddDocsOpen(false)}
          onUpdated={() => qc.invalidateQueries({ queryKey: ["tabular-review", reviewId] })}
        />
      ) : null}
    </div>
  );
}
