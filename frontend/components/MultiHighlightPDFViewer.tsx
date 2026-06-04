"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatReference } from "@/lib/picardApi";
import { cn } from "@/lib/utils";
import { BboxOverlay } from "@/components/pdf/BboxOverlay";
import { dedupeByBboxOverlap, isValidBbox } from "@/components/pdf/bbox-utils";
import { PdfPageViewer } from "@/components/pdf/PdfPageViewer";

type Props = {
  documentId: string | null;
  highlights?: ChatReference[];
  activeIndex?: number | null;
  activeRef?: ChatReference | null;
};

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

  const dedupe = dedupeByBboxOverlap as (items: ChatReference[]) => ChatReference[];
  return dedupe(onPage);
}

export function MultiHighlightPDFViewer({
  documentId,
  highlights = [],
  activeIndex,
  activeRef,
}: Props) {
  const [page, setPage] = useState(1);
  const [pageHeight, setPageHeight] = useState(0);
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  const goToReference = useCallback((ref: ChatReference) => {
    setPage(ref.page);
  }, []);

  useEffect(() => {
    if (activeRef) {
      goToReference(activeRef);
      return;
    }
    if (activeIndex == null) return;
    const ref = highlights.find((h) => h.index === activeIndex);
    if (ref) goToReference(ref);
  }, [activeRef, activeIndex, highlights, goToReference]);

  useEffect(() => {
    if (!activeRef?.bbox || !isValidBbox(activeRef.bbox) || !scrollAreaRef.current || !pageHeight) return;
    const scrollEl = scrollAreaRef.current;
    const targetTop = activeRef.bbox.y0 * pageHeight - scrollEl.clientHeight / 3;
    scrollEl.scrollTo({ top: Math.max(0, targetTop), behavior: "smooth" });
  }, [activeRef, page, pageHeight]);

  if (!documentId) {
    return null;
  }

  const pageHighlights = highlightsForPage(highlights, page, activeIndex);

  return (
    <PdfPageViewer
      documentId={documentId}
      page={page}
      onPageChange={setPage}
      scrollAreaRef={scrollAreaRef}
      onPageHeightChange={setPageHeight}
      header={
        activeRef ? (
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
        ) : undefined
      }
    >
      {({ pageWidth, pageHeight: renderedHeight }) =>
        pageHighlights.map((h) =>
          h.bbox && isValidBbox(h.bbox) ? (
            <BboxOverlay
              key={h.index}
              bbox={h.bbox}
              width={pageWidth}
              height={renderedHeight}
              active={h.index === activeIndex}
              className={cn(
                h.index === activeIndex
                  ? "border-neutral-900 bg-neutral-400/30"
                  : "border-neutral-400 bg-neutral-400/15"
              )}
            />
          ) : null
        )
      }
    </PdfPageViewer>
  );
}
