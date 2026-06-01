"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";
import type { ChatReference } from "@/lib/picardApi";
import { cn } from "@/lib/utils";

pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Bbox = { x0: number; y0: number; x1: number; y1: number };

function isValidBbox(bbox: Record<string, number> | null | undefined): bbox is Bbox {
  if (!bbox || Object.keys(bbox).length === 0) return false;
  const { x0, y0, x1, y1 } = bbox;
  if ([x0, y0, x1, y1].some((v) => typeof v !== "number" || Number.isNaN(v))) return false;
  return x1 > x0 && y1 > y0;
}

function bboxOverlapRatio(a: Bbox, b: Bbox): number {
  const xOverlap = Math.max(0, Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0));
  const yOverlap = Math.max(0, Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0));
  const overlapArea = xOverlap * yOverlap;
  const minArea = Math.min((a.x1 - a.x0) * (a.y1 - a.y0), (b.x1 - b.x0) * (b.y1 - b.y0));
  if (minArea <= 0) return 0;
  return overlapArea / minArea;
}

function highlightsForPage(
  highlights: ChatReference[],
  page: number,
  activeIndex?: number | null
): ChatReference[] {
  const onPage = highlights.filter(
    (h) => h.page === page && isValidBbox(h.bbox as Record<string, number> | null | undefined)
  );

  if (activeIndex != null) {
    const active = onPage.find((h) => h.index === activeIndex);
    return active ? [active] : [];
  }

  const deduped: ChatReference[] = [];
  for (const h of onPage) {
    const overlapsExisting = deduped.some(
      (existing) => existing.bbox && h.bbox && bboxOverlapRatio(existing.bbox, h.bbox) > 0.5
    );
    if (!overlapsExisting) deduped.push(h);
  }
  return deduped;
}

type Props = {
  documentId: string | null;
  highlights?: ChatReference[];
  activeIndex?: number | null;
  activeRef?: ChatReference | null;
};

function BboxOverlay({
  bbox,
  width,
  height,
  active,
}: {
  bbox: Bbox;
  width: number;
  height: number;
  active: boolean;
}) {
  const left = bbox.x0 * width;
  const top = bbox.y0 * height;
  const w = (bbox.x1 - bbox.x0) * width;
  const h = (bbox.y1 - bbox.y0) * height;
  return (
    <div
      className={cn(
        "pointer-events-none absolute border-2",
        active
          ? "border-amber-500 bg-amber-200/30"
          : "border-neutral-400 bg-neutral-400/15"
      )}
      style={{ left, top, width: w, height: h }}
    />
  );
}

export function MultiHighlightPDFViewer({
  documentId,
  highlights = [],
  activeIndex,
  activeRef,
}: Props) {
  const [page, setPage] = useState(1);
  const [numPages, setNumPages] = useState(0);
  const [pageWidth, setPageWidth] = useState(480);
  const [pageHeight, setPageHeight] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const goToReference = useCallback((ref: ChatReference) => {
    setPage(ref.page);
  }, []);

  useEffect(() => {
    if (activeIndex == null) return;
    const ref = highlights.find((h) => h.index === activeIndex);
    if (ref) goToReference(ref);
  }, [activeIndex, highlights, goToReference]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setPageWidth(el.clientWidth - 16));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  if (!documentId) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-neutral-500">
        Select a citation to view the PDF
      </div>
    );
  }

  const pageHighlights = highlightsForPage(highlights, page, activeIndex);
  const fileUrl = `${API_URL}/documents/${documentId}/file`;
  const overlayHeight = pageHeight || pageWidth * 1.294;

  return (
    <div ref={containerRef} className="flex h-full flex-col overflow-hidden bg-neutral-100">
      {activeRef && (
        <div className="border-b border-neutral-200 bg-white px-3 py-2 text-xs text-neutral-600">
          <div className="flex flex-wrap items-baseline gap-x-1">
            {activeRef.document_name && (
              <span className="font-medium text-neutral-800">{activeRef.document_name}</span>
            )}
            {activeRef.document_name && <span className="text-neutral-400">·</span>}
            <span>Page {activeRef.page}</span>
          </div>
          {activeRef.pinpoint_quote && (
            <p className="mt-1 line-clamp-3 text-neutral-500">{activeRef.pinpoint_quote}</p>
          )}
        </div>
      )}
      <div className="flex items-center gap-2 border-b border-neutral-200 bg-white px-3 py-2 text-sm">
        <button
          type="button"
          className="rounded px-2 py-1 hover:bg-neutral-100 disabled:opacity-40"
          disabled={page <= 1}
          onClick={() => setPage((p) => Math.max(1, p - 1))}
        >
          Prev
        </button>
        <span>
          Page {page} / {numPages || "?"}
        </span>
        <button
          type="button"
          className="rounded px-2 py-1 hover:bg-neutral-100 disabled:opacity-40"
          disabled={page >= numPages}
          onClick={() => setPage((p) => Math.min(numPages, p + 1))}
        >
          Next
        </button>
      </div>
      <div className="relative flex-1 overflow-auto p-2">
        <Document file={fileUrl} onLoadSuccess={(d) => setNumPages(d.numPages)} loading="Loading PDF…">
          <div className="relative mx-auto" style={{ width: pageWidth }}>
            <Page
              pageNumber={page}
              width={pageWidth}
              renderTextLayer={false}
              onRenderSuccess={(pdfPage) => {
                setPageHeight(pdfPage.height);
              }}
            />
            {pageHighlights.map((h) =>
              h.bbox && isValidBbox(h.bbox) ? (
                <BboxOverlay
                  key={h.index}
                  bbox={h.bbox}
                  width={pageWidth}
                  height={overlayHeight}
                  active={h.index === activeIndex}
                />
              ) : null
            )}
          </div>
        </Document>
      </div>
    </div>
  );
}
