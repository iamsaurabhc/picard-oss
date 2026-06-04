"use client";

import { useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";
import { documentFileUrl } from "@/lib/picardApi";

// Must match react-pdf's pdfjs-dist (see scripts/copy-pdf-worker.sh). Version pinned in package.json.
pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";

type Props = {
  documentId: string;
  page: number;
  onPageChange: (page: number) => void;
  header?: React.ReactNode;
  toolbarExtra?: React.ReactNode;
  emptyMessage?: string;
  scrollAreaRef?: React.RefObject<HTMLDivElement | null>;
  onPageHeightChange?: (height: number) => void;
  children?: (dims: { pageWidth: number; pageHeight: number }) => React.ReactNode;
};

export function PdfPageViewer({
  documentId,
  page,
  onPageChange,
  header,
  toolbarExtra,
  emptyMessage = "No document selected",
  scrollAreaRef,
  onPageHeightChange,
  children,
}: Props) {
  const [numPages, setNumPages] = useState(0);
  const [pageWidth, setPageWidth] = useState(480);
  const [pageHeight, setPageHeight] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

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
        {emptyMessage}
      </div>
    );
  }

  const fileUrl = documentFileUrl(documentId);
  const overlayHeight = pageHeight || pageWidth * 1.294;

  return (
    <div ref={containerRef} className="flex h-full flex-col overflow-hidden bg-neutral-100">
      {header}
      <div className="flex items-center gap-2 border-b border-neutral-200 bg-white px-3 py-2 text-sm">
        <button
          type="button"
          className="rounded px-2 py-1 hover:bg-neutral-100 disabled:opacity-40"
          disabled={page <= 1}
          onClick={() => onPageChange(Math.max(1, page - 1))}
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
          onClick={() => onPageChange(Math.min(numPages, page + 1))}
        >
          Next
        </button>
        {toolbarExtra}
      </div>
      <div ref={scrollAreaRef} className="relative flex-1 overflow-auto p-2">
        <Document file={fileUrl} onLoadSuccess={(d) => setNumPages(d.numPages)} loading="Loading PDF…">
          <div className="relative mx-auto" style={{ width: pageWidth }}>
            <Page
              pageNumber={page}
              width={pageWidth}
              renderTextLayer={false}
              onRenderSuccess={(pdfPage) => {
                setPageHeight(pdfPage.height);
                onPageHeightChange?.(pdfPage.height);
              }}
            />
            {children?.({ pageWidth, pageHeight: overlayHeight })}
          </div>
        </Document>
      </div>
    </div>
  );
}
