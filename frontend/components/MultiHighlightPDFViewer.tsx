"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatReference } from "@/lib/picardApi";
import { BboxOverlay } from "@/components/pdf/BboxOverlay";
import { dedupeByBboxOverlap, isValidBbox } from "@/components/pdf/bbox-utils";
import { PdfPageViewer, type PdfPageViewerHandle } from "@/components/pdf/PdfPageViewer";

type Props = {
  documentId: string | null;
  highlights?: ChatReference[];
  activeIndex?: number | null;
  activeRef?: ChatReference | null;
};

function bboxKey(bbox: Record<string, number> | null | undefined): string {
  if (!bbox || !isValidBbox(bbox)) return "";
  return `${bbox.x0},${bbox.y0},${bbox.x1},${bbox.y1}`;
}

/** Overlays to draw on a single PDF page. Bboxes are normalized to that page only. */
function overlaysForPage(
  page: number,
  highlights: ChatReference[],
  activeIndex?: number | null,
  activeRef?: ChatReference | null
): ChatReference[] {
  if (activeRef?.page === page) {
    const multi = (activeRef.highlight_bboxes ?? []).filter((bbox) =>
      isValidBbox(bbox)
    );
    if (multi.length) {
      return multi.map((bbox) => ({ ...activeRef, bbox }));
    }
    if (isValidBbox(activeRef.bbox)) {
      return [activeRef];
    }
    return [];
  }

  const expanded: ChatReference[] = [];
  for (const h of highlights) {
    if (h.page !== page) continue;
    const extra = h.highlight_bboxes;
    if (extra?.length) {
      for (const bbox of extra) {
        if (isValidBbox(bbox) && expanded.length < 5) {
          expanded.push({ ...h, bbox });
        }
      }
    } else if (isValidBbox(h.bbox)) {
      expanded.push(h);
    }
  }

  // Guard: if highlights cover >60% of page height, they're likely false expansion
  if (expanded.length > 1) {
    const totalHeight = expanded.reduce((sum, h) => {
      const b = h.bbox!;
      return sum + (b.y1 - b.y0);
    }, 0);
    if (totalHeight > 0.6) {
      // Too much coverage — fall back to just the first (primary) highlight
      return expanded.slice(0, 1);
    }
  }

  if (activeIndex != null && !activeRef) {
    const active = expanded.find((h) => h.index === activeIndex);
    return active ? [active] : [];
  }

  const dedupe = dedupeByBboxOverlap as (items: ChatReference[]) => ChatReference[];
  return dedupe(expanded);
}

export function MultiHighlightPDFViewer({
  documentId,
  highlights = [],
  activeIndex,
  activeRef,
}: Props) {
  const [page, setPage] = useState(1);
  const viewerRef = useRef<PdfPageViewerHandle>(null);

  useEffect(() => {
    setPage(1);
  }, [documentId]);

  const goToReference = useCallback((ref: ChatReference) => {
    setPage(ref.page);
    const bboxY0 =
      ref.bbox && isValidBbox(ref.bbox) ? ref.bbox.y0 : undefined;
    viewerRef.current?.scrollToPage(ref.page, bboxY0);
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

  if (!documentId) {
    return null;
  }

  return (
    <PdfPageViewer
      ref={viewerRef}
      documentId={documentId}
      page={page}
      onPageChange={setPage}
      scrollMode="continuous"
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
      {({ pageWidth, pageHeight, pageNumber }) => {
        const overlays = overlaysForPage(
          pageNumber,
          highlights,
          activeIndex,
          activeRef
        );
        return overlays.map((h) => (
          <BboxOverlay
            key={`${h.chunk_id}-${bboxKey(h.bbox)}-${pageNumber}`}
            bbox={h.bbox!}
            width={pageWidth}
            height={pageHeight}
            active={
              activeRef != null
                ? h.index === activeRef.index
                : h.index === activeIndex
            }
          />
        ));
      }}
    </PdfPageViewer>
  );
}
