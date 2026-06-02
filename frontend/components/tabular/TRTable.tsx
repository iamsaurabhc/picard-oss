"use client";

import { forwardRef, useImperativeHandle, useRef } from "react";
import { Loader2, Plus, Upload } from "lucide-react";
import type { DocumentRecord, TabularCell, TabularColumn } from "@/lib/picardApi";
import { TabularCellComponent } from "./TabularCell";

const COL_W = "w-[280px] shrink-0";
const CHECK_W = "w-8 shrink-0";
const DOC_COL_W = "w-[240px] shrink-0";

export type TRTableHandle = {
  scrollToCell: (colIdx: number, rowIdx: number) => void;
};

type Props = {
  loading: boolean;
  columns: TabularColumn[];
  documents: DocumentRecord[];
  cells: TabularCell[];
  selectedDocIds: string[];
  uploadingFilenames?: string[];
  dragOverFiles?: boolean;
  highlightedCell?: { colIdx: number; rowIdx: number } | null;
  onSelectionChange: (ids: string[]) => void;
  onExpand: (cell: TabularCell) => void;
  onCitationClick: (cell: TabularCell, page: number, quote: string) => void;
  onAddColumn: () => void;
  onAddDocuments: () => void;
  onDropFiles?: (files: FileList) => void;
};

export const TRTable = forwardRef<TRTableHandle, Props>(function TRTable(
  {
    loading,
    columns,
    documents,
    cells,
    selectedDocIds,
    uploadingFilenames = [],
    dragOverFiles = false,
    highlightedCell,
    onSelectionChange,
    onExpand,
    onCitationClick,
    onAddColumn,
    onAddDocuments,
    onDropFiles,
  },
  ref
) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useImperativeHandle(ref, () => ({
    scrollToCell(colIdx: number, rowIdx: number) {
      const container = scrollRef.current;
      if (!container) return;
      const rows = container.querySelectorAll<HTMLElement>("[data-tr-row]");
      const row = rows[rowIdx];
      if (row) {
        container.scrollTo({ top: Math.max(0, row.offsetTop - 40), behavior: "smooth" });
      }
      const colLeft = 32 + 240 + colIdx * 280;
      container.scrollTo({ left: Math.max(0, colLeft - container.clientWidth / 2), behavior: "smooth" });
    },
  }));

  function getCell(docId: string, columnKey: string) {
    return cells.find((c) => c.document_id === docId && c.column_key === columnKey);
  }

  const allSelected = documents.length > 0 && documents.every((d) => selectedDocIds.includes(d.id));

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center p-12 text-neutral-500">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading review…
      </div>
    );
  }

  return (
    <div
      className={`relative flex flex-1 flex-col overflow-hidden border-t border-neutral-200 ${
        dragOverFiles ? "bg-blue-50/50" : ""
      }`}
      onDragOver={(e) => {
        e.preventDefault();
      }}
      onDrop={(e) => {
        e.preventDefault();
        if (e.dataTransfer.files.length) onDropFiles?.(e.dataTransfer.files);
      }}
    >
      {dragOverFiles ? (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center border-2 border-dashed border-blue-400 bg-blue-50/80">
          <p className="flex items-center gap-2 text-sm font-medium text-blue-700">
            <Upload className="h-4 w-4" />
            Drop PDFs to add documents
          </p>
        </div>
      ) : null}

      <div ref={scrollRef} className="flex-1 overflow-auto">
        <div className="sticky top-0 z-20 flex min-w-max border-b border-neutral-200 bg-neutral-50 text-xs font-medium text-neutral-600">
          <div className={`${CHECK_W} flex items-center justify-center border-r border-neutral-200 p-2`}>
            <input
              type="checkbox"
              checked={allSelected}
              onChange={() =>
                onSelectionChange(allSelected ? [] : documents.map((d) => d.id))
              }
            />
          </div>
          <div className={`${DOC_COL_W} sticky left-8 z-30 border-r border-neutral-200 bg-neutral-50 px-3 py-2`}>
            Document
          </div>
          {columns.map((col) => (
            <div key={col.key} className={`${COL_W} border-r border-neutral-200 px-3 py-2`}>
              {col.label}
            </div>
          ))}
          <button
            type="button"
            className="flex items-center gap-1 px-4 py-2 text-neutral-500 hover:text-neutral-900"
            onClick={onAddColumn}
          >
            <Plus className="h-3.5 w-3.5" />
            Column
          </button>
        </div>

        {documents.map((doc, rowIdx) => (
          <div key={doc.id} data-tr-row className="flex min-w-max border-b border-neutral-100">
            <div className={`${CHECK_W} flex items-start border-r border-neutral-100 p-2 pt-3`}>
              <input
                type="checkbox"
                checked={selectedDocIds.includes(doc.id)}
                onChange={() => {
                  if (selectedDocIds.includes(doc.id)) {
                    onSelectionChange(selectedDocIds.filter((id) => id !== doc.id));
                  } else {
                    onSelectionChange([...selectedDocIds, doc.id]);
                  }
                }}
              />
            </div>
            <div
              className={`${DOC_COL_W} sticky left-8 z-10 border-r border-neutral-100 bg-white px-3 py-3 text-sm font-medium text-neutral-900`}
            >
              {doc.file_name}
              {doc.parse_status !== "done" ? (
                <span className="mt-1 block text-xs font-normal text-amber-600">{doc.parse_status}</span>
              ) : null}
            </div>
            {columns.map((col, colIdx) => {
              const cell = getCell(doc.id, col.key);
              if (!cell) {
                return (
                  <div key={col.key} className={`${COL_W} border-r border-neutral-100 bg-neutral-50/50`} />
                );
              }
              return (
                <div key={col.key} className={`${COL_W} border-r border-neutral-100`}>
                  <TabularCellComponent
                    cell={cell}
                    column={col}
                    highlighted={
                      highlightedCell?.colIdx === colIdx && highlightedCell?.rowIdx === rowIdx
                    }
                    onExpand={() => onExpand(cell)}
                    onCitationClick={(page, quote) => onCitationClick(cell, page, quote)}
                  />
                </div>
              );
            })}
          </div>
        ))}

        {uploadingFilenames.map((name) => (
          <div key={name} className="flex min-w-max border-b border-neutral-100 bg-neutral-50">
            <div className={`${CHECK_W} border-r border-neutral-100`} />
            <div className={`${DOC_COL_W} sticky left-8 border-r border-neutral-100 px-3 py-3 text-sm text-neutral-500`}>
              <Loader2 className="mr-2 inline h-3 w-3 animate-spin" />
              Uploading {name}…
            </div>
            {columns.map((col) => (
              <div key={col.key} className={`${COL_W} border-r border-neutral-100`} />
            ))}
          </div>
        ))}

        {documents.length === 0 ? (
          <div className="p-12 text-center text-sm text-neutral-500">
            <p className="mb-3">No documents in this review.</p>
            <button type="button" className="text-blue-600 hover:underline" onClick={onAddDocuments}>
              Add documents
            </button>
            {onDropFiles ? (
              <p className="mt-2 text-xs">or drag and drop PDFs here</p>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
});
