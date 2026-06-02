"use client";

import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Loader2, RefreshCw, X } from "lucide-react";
import type { ChatReference, DocumentRecord, TabularCell, TabularColumn } from "@/lib/picardApi";
import { picardApi } from "@/lib/picardApi";
import { MultiHighlightPDFViewer } from "@/components/MultiHighlightPDFViewer";
import { preprocessCitations } from "./citation-utils";

type Props = {
  cell: TabularCell;
  document: DocumentRecord;
  column: TabularColumn;
  columns: TabularColumn[];
  onClose: () => void;
  onNavigate: (columnKey: string) => void;
  onRegenerate?: () => Promise<void>;
  initialCitation?: { page: number; quote: string };
};

export function TRSidePanel({
  cell,
  document,
  column,
  columns,
  onClose,
  onNavigate,
  onRegenerate,
  initialCitation,
}: Props) {
  const [regenerating, setRegenerating] = useState(false);
  const [highlights, setHighlights] = useState<ChatReference[]>([]);
  const [activeRef, setActiveRef] = useState<ChatReference | null>(null);

  const colIdx = columns.findIndex((c) => c.key === column.key);
  const prevCol = colIdx > 0 ? columns[colIdx - 1] : null;
  const nextCol = colIdx < columns.length - 1 ? columns[colIdx + 1] : null;

  const summary = cell.summary || "";
  const { citations } = preprocessCitations(summary);

  useEffect(() => {
    let cancelled = false;
    async function loadHighlights() {
      if (!cell.source_chunk_ids.length) {
        if (initialCitation) {
          const chunks = await picardApi.getDocumentChunks(document.id, {
            page: initialCitation.page,
          });
          const match = chunks.find((c) => c.page_number === initialCitation.page);
          if (!cancelled && match) {
            const ref: ChatReference = {
              index: 1,
              chunk_id: match.id,
              document_id: document.id,
              page: match.page_number,
              bbox: match.bbox,
              preview: initialCitation.quote,
              document_name: document.file_name,
            };
            setHighlights([ref]);
            setActiveRef(ref);
          }
        }
        return;
      }
      const refs: ChatReference[] = [];
      for (let i = 0; i < cell.source_chunk_ids.length; i++) {
        const chunkId = cell.source_chunk_ids[i];
        const pages = citations.map((c) => c.page);
        const page = pages[i] ?? citations[0]?.page ?? 1;
        const chunks = await picardApi.getDocumentChunks(document.id, { page });
        const chunk = chunks.find((c) => c.id === chunkId) ?? chunks[0];
        if (chunk) {
          refs.push({
            index: i + 1,
            chunk_id: chunk.id,
            document_id: document.id,
            page: chunk.page_number,
            bbox: chunk.bbox,
            preview: citations[i]?.quote ?? chunk.text_content.slice(0, 200),
            document_name: document.file_name,
          });
        }
      }
      if (!cancelled) {
        setHighlights(refs);
        if (initialCitation && refs.length) {
          const match = refs.find((r) => r.page === initialCitation.page) ?? refs[0];
          setActiveRef(match);
        } else if (refs.length) {
          setActiveRef(refs[0]);
        }
      }
    }
    loadHighlights();
    return () => {
      cancelled = true;
    };
  }, [cell.id, cell.source_chunk_ids, document.id, document.file_name, initialCitation, citations]);

  return (
    <div className="flex h-full w-[min(520px,45vw)] shrink-0 flex-col border-l border-neutral-200 bg-white">
      <div className="flex items-center gap-2 border-b border-neutral-200 px-4 py-3">
        <button type="button" onClick={onClose} className="rounded p-1 hover:bg-neutral-100">
          <X className="h-4 w-4" />
        </button>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{column.label}</p>
          <p className="truncate text-xs text-neutral-500">{document.file_name}</p>
        </div>
        {prevCol ? (
          <button
            type="button"
            className="rounded p-1 hover:bg-neutral-100"
            onClick={() => onNavigate(prevCol.key)}
            title={prevCol.label}
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
        ) : null}
        {nextCol ? (
          <button
            type="button"
            className="rounded p-1 hover:bg-neutral-100"
            onClick={() => onNavigate(nextCol.key)}
            title={nextCol.label}
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        ) : null}
        {onRegenerate ? (
          <button
            type="button"
            className="rounded p-1 hover:bg-neutral-100"
            disabled={regenerating}
            onClick={async () => {
              setRegenerating(true);
              try {
                await onRegenerate();
              } finally {
                setRegenerating(false);
              }
            }}
          >
            {regenerating ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
          </button>
        ) : null}
      </div>

      <div className="flex-1 overflow-y-auto p-4 text-sm">
        <h3 className="mb-1 text-xs font-medium uppercase text-neutral-500">Summary</h3>
        <p className="mb-4 whitespace-pre-wrap leading-relaxed">{summary.replace(/\[\[[^\]]+\]\]/g, "")}</p>
        {cell.reasoning ? (
          <>
            <h3 className="mb-1 text-xs font-medium uppercase text-neutral-500">Reasoning</h3>
            <p className="mb-4 text-neutral-600">{cell.reasoning}</p>
          </>
        ) : null}
        {citations.length > 0 ? (
          <div className="mb-4 flex flex-wrap gap-2">
            {citations.map((c, i) => (
              <button
                key={i}
                type="button"
                className="rounded-full bg-blue-50 px-2 py-0.5 text-xs text-blue-700 hover:bg-blue-100"
                onClick={() => {
                  const ref = highlights.find((h) => h.page === c.page);
                  if (ref) setActiveRef(ref);
                }}
              >
                p.{c.page}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      <div className="h-[45vh] min-h-[280px] border-t border-neutral-200">
        <MultiHighlightPDFViewer
          documentId={document.id}
          highlights={highlights}
          activeRef={activeRef}
        />
      </div>
    </div>
  );
}
