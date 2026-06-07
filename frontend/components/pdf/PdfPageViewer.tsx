"use client";

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/TextLayer.css";
import "react-pdf/dist/Page/AnnotationLayer.css";
import { documentFileUrl } from "@/lib/picardApi";

pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";

const VIRTUALIZE_THRESHOLD = 50;
const VIRTUAL_WINDOW = 2;
const PAGE_GAP = 8;

export type PageDims = {
  pageWidth: number;
  pageHeight: number;
  pageNumber: number;
};

export type PdfPageViewerHandle = {
  scrollToPage: (page: number, bboxY0?: number) => void;
  getPageOffsetTop: (page: number) => number | null;
  getPageHeight: (page: number) => number | null;
};

type Props = {
  documentId: string;
  page: number;
  onPageChange: (page: number) => void;
  scrollMode?: "single" | "continuous";
  header?: React.ReactNode;
  toolbarExtra?: React.ReactNode;
  emptyMessage?: string;
  scrollAreaRef?: React.RefObject<HTMLDivElement | null>;
  onPageHeightChange?: (height: number) => void;
  children?: (dims: PageDims) => React.ReactNode;
};

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export const PdfPageViewer = forwardRef<PdfPageViewerHandle, Props>(function PdfPageViewer(
  {
    documentId,
    page,
    onPageChange,
    scrollMode = "continuous",
    header,
    toolbarExtra,
    emptyMessage = "No document selected",
    scrollAreaRef: externalScrollRef,
    onPageHeightChange,
    children,
  },
  ref
) {
  const [numPages, setNumPages] = useState(0);
  const [pageWidth, setPageWidth] = useState(480);
  const [pageHeights, setPageHeights] = useState<Record<number, number>>({});
  const [visibleRange, setVisibleRange] = useState({ start: 1, end: 5 });
  const containerRef = useRef<HTMLDivElement>(null);
  const internalScrollRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const syncingFromProp = useRef(false);
  const lastReportedPage = useRef(page);
  const pendingScrollRef = useRef<{ targetPage: number; bboxY0?: number } | null>(null);
  const pageHeightsRef = useRef(pageHeights);

  const scrollRef = externalScrollRef ?? internalScrollRef;

  useEffect(() => {
    pageHeightsRef.current = pageHeights;
  }, [pageHeights]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setPageWidth(el.clientWidth - 16));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const defaultPageHeight = useCallback(() => pageWidth * 1.294, [pageWidth]);

  const cumulativeOffsetTop = useCallback(
    (targetPage: number, heights: Record<number, number>) => {
      const fallback = defaultPageHeight();
      let offset = 0;
      for (let p = 1; p < targetPage; p++) {
        offset += (heights[p] ?? fallback) + PAGE_GAP;
      }
      return offset;
    },
    [defaultPageHeight]
  );

  const isPlaceholderPage = useCallback((pageNumber: number) => {
    const el = pageRefs.current[pageNumber];
    return el?.textContent?.includes("Loading page") ?? false;
  }, []);

  const executeScroll = useCallback(
    (targetPage: number, bboxY0?: number) => {
      const scrollEl = scrollRef.current;
      if (!scrollEl) return false;

      const pageEl = pageRefs.current[targetPage];
      const heights = pageHeightsRef.current;
      const placeholder = isPlaceholderPage(targetPage);
      const pageHeight = heights[targetPage] ?? pageEl?.offsetHeight ?? defaultPageHeight();
      const cumulativeTop = cumulativeOffsetTop(targetPage, heights);
      const pageTop =
        !placeholder && pageEl && pageEl.offsetTop > 0 ? pageEl.offsetTop : cumulativeTop;

      let top = pageTop;
      if (bboxY0 != null && pageHeight > 0) {
        top = pageTop + bboxY0 * pageHeight - scrollEl.clientHeight / 3;
      }

      scrollEl.scrollTo({
        top: Math.max(0, top),
        behavior: prefersReducedMotion() ? "auto" : "smooth",
      });

      return !placeholder && !!heights[targetPage];
    },
    [scrollRef, cumulativeOffsetTop, defaultPageHeight, isPlaceholderPage]
  );

  const finishPendingSync = useCallback(() => {
    setTimeout(() => {
      syncingFromProp.current = false;
    }, 400);
  }, []);

  const scrollToPage = useCallback(
    (targetPage: number, bboxY0?: number) => {
      syncingFromProp.current = true;
      lastReportedPage.current = targetPage;
      pendingScrollRef.current = { targetPage, bboxY0 };

      if (numPages > VIRTUALIZE_THRESHOLD) {
        setVisibleRange({
          start: Math.max(1, targetPage - VIRTUAL_WINDOW),
          end: Math.min(numPages, targetPage + VIRTUAL_WINDOW),
        });
      }

      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          const done = executeScroll(targetPage, bboxY0);
          if (done) {
            pendingScrollRef.current = null;
            finishPendingSync();
          }
        });
      });
    },
    [numPages, executeScroll, finishPendingSync]
  );

  useImperativeHandle(
    ref,
    () => ({
      scrollToPage,
      getPageOffsetTop: (p) => {
        const el = pageRefs.current[p];
        if (el && !isPlaceholderPage(p) && el.offsetTop > 0) return el.offsetTop;
        return cumulativeOffsetTop(p, pageHeightsRef.current);
      },
      getPageHeight: (p) => pageHeightsRef.current[p] ?? pageRefs.current[p]?.offsetHeight ?? null,
    }),
    [scrollToPage, cumulativeOffsetTop, isPlaceholderPage]
  );

  useEffect(() => {
    if (scrollMode !== "continuous") return;
    if (page === lastReportedPage.current) return;
    lastReportedPage.current = page;
  }, [page, scrollMode]);

  useEffect(() => {
    if (scrollMode !== "continuous" || !numPages) return;
    const scrollEl = scrollRef.current;
    if (!scrollEl) return;

    const updateRange = () => {
      const scrollTop = scrollEl.scrollTop;
      const viewHeight = scrollEl.clientHeight;
      const centers: { page: number; dist: number }[] = [];

      for (let p = 1; p <= numPages; p++) {
        const el = pageRefs.current[p];
        if (!el) continue;
        const top = el.offsetTop;
        const height = el.offsetHeight || pageHeights[p] || 0;
        const center = top + height / 2;
        centers.push({ page: p, dist: Math.abs(center - (scrollTop + viewHeight / 2)) });
      }

      if (centers.length === 0) return;

      centers.sort((a, b) => a.dist - b.dist);
      const current = centers[0].page;

      if (!syncingFromProp.current && current !== lastReportedPage.current) {
        lastReportedPage.current = current;
        onPageChange(current);
        const h = pageHeights[current];
        if (h) onPageHeightChange?.(h);
      }

      if (numPages > VIRTUALIZE_THRESHOLD && !syncingFromProp.current && !pendingScrollRef.current) {
        const start = Math.max(1, current - VIRTUAL_WINDOW);
        const end = Math.min(numPages, current + VIRTUAL_WINDOW);
        setVisibleRange((prev) =>
          prev.start === start && prev.end === end ? prev : { start, end }
        );
      }
    };

    const onScroll = () => requestAnimationFrame(updateRange);
    scrollEl.addEventListener("scroll", onScroll, { passive: true });
    updateRange();
    return () => scrollEl.removeEventListener("scroll", onScroll);
  }, [scrollMode, numPages, scrollRef, onPageChange, onPageHeightChange, pageHeights]);

  useEffect(() => {
    setNumPages(0);
    setPageHeights({});
    pageRefs.current = {};
    lastReportedPage.current = 1;
    pendingScrollRef.current = null;
  }, [documentId]);

  useEffect(() => {
    if (numPages <= VIRTUALIZE_THRESHOLD) {
      setVisibleRange({ start: 1, end: numPages });
    } else {
      setVisibleRange({ start: 1, end: Math.min(5, numPages) });
    }
  }, [numPages, documentId]);

  const setPageHeight = useCallback(
    (pageNumber: number, height: number) => {
      setPageHeights((prev) => {
        if (prev[pageNumber] === height) return prev;
        const next = { ...prev, [pageNumber]: height };
        pageHeightsRef.current = next;
        return next;
      });
      if (pageNumber === page) {
        onPageHeightChange?.(height);
      }

      const pending = pendingScrollRef.current;
      if (pending?.targetPage === pageNumber) {
        requestAnimationFrame(() => {
          executeScroll(pending.targetPage, pending.bboxY0);
          pendingScrollRef.current = null;
          finishPendingSync();
        });
      }
    },
    [page, onPageHeightChange, executeScroll, finishPendingSync]
  );

  const goPrev = () => {
    const next = Math.max(1, page - 1);
    scrollToPage(next);
    onPageChange(next);
  };

  const goNext = () => {
    const next = Math.min(numPages, page + 1);
    scrollToPage(next);
    onPageChange(next);
  };

  if (!documentId) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-neutral-500">
        {emptyMessage}
      </div>
    );
  }

  const fileUrl = documentFileUrl(documentId);
  const singlePageHeight = pageHeights[page] || pageWidth * 1.294;

  const renderPage = (pageNumber: number, placeholder = false) => {
    const height = pageHeights[pageNumber] || pageWidth * 1.294;
    if (placeholder) {
      return (
        <div
          key={`placeholder-${pageNumber}`}
          ref={(el) => {
            pageRefs.current[pageNumber] = el;
          }}
          className="mx-auto flex items-center justify-center bg-white text-xs text-neutral-400"
          style={{ width: pageWidth, height }}
          data-page={pageNumber}
        >
          Loading page…
        </div>
      );
    }

    return (
      <div
        key={`page-${pageNumber}`}
        ref={(el) => {
          pageRefs.current[pageNumber] = el;
        }}
        className="relative mx-auto"
        style={{ width: pageWidth }}
        data-page={pageNumber}
      >
        <Page
          pageNumber={pageNumber}
          width={pageWidth}
          renderTextLayer={false}
          renderAnnotationLayer={false}
          onRenderSuccess={(pdfPage) => setPageHeight(pageNumber, pdfPage.height)}
        />
        {children?.({ pageWidth, pageHeight: height, pageNumber })}
      </div>
    );
  };

  return (
    <div ref={containerRef} className="flex h-full flex-col overflow-hidden bg-neutral-100">
      {header}
      <div className="flex items-center gap-2 border-b border-neutral-200 bg-white px-3 py-2 text-sm">
        <button
          type="button"
          className="rounded px-2 py-1 hover:bg-neutral-100 disabled:opacity-40"
          disabled={page <= 1}
          onClick={goPrev}
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
          onClick={goNext}
        >
          Next
        </button>
        {toolbarExtra}
      </div>
      <div ref={scrollRef} className="relative flex-1 overflow-auto p-2">
        <Document
          file={fileUrl}
          onLoadSuccess={(d) => setNumPages(d.numPages)}
          loading="Loading PDF…"
        >
          {scrollMode === "single" ? (
            <div className="relative mx-auto" style={{ width: pageWidth }}>
              <Page
                pageNumber={page}
                width={pageWidth}
                renderTextLayer={false}
                renderAnnotationLayer={false}
                onRenderSuccess={(pdfPage) => setPageHeight(page, pdfPage.height)}
              />
              {children?.({ pageWidth, pageHeight: singlePageHeight, pageNumber: page })}
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {Array.from({ length: numPages }, (_, i) => i + 1).map((pageNumber) => {
                const inRange =
                  numPages <= VIRTUALIZE_THRESHOLD ||
                  (pageNumber >= visibleRange.start && pageNumber <= visibleRange.end);
                return inRange ? renderPage(pageNumber) : renderPage(pageNumber, true);
              })}
            </div>
          )}
        </Document>
      </div>
    </div>
  );
});

PdfPageViewer.displayName = "PdfPageViewer";
