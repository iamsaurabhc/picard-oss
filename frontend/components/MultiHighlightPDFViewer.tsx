"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatReference } from "@/lib/picardApi";
import { BboxOverlay } from "@/components/pdf/BboxOverlay";
import { dedupeByBboxOverlap, isValidBbox, type Bbox } from "@/components/pdf/bbox-utils";
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

function bboxDedupKey(bbox: Bbox): string {
  const r = (n: number) => Math.round(n * 10000);
  return `${r(bbox.x0)}_${r(bbox.y0)}_${r(bbox.x1)}_${r(bbox.y1)}`;
}

const NEIGHBOR_Y_GAP = 0.025;
const MAX_EXPANSION_BBOXES = 3;
const MAX_PAGE_COVERAGE = 0.6;

/**
 * Given seed bboxes for the active page, expand to vertically adjacent
 * page_chunks within a tight y-gap so a citation lands on its full paragraph
 * (1 chunk above + the seed + 1 below) rather than a single sentence box.
 */
function expandSeedBboxes(seeds: Bbox[], ref: ChatReference): Bbox[] {
  const pageChunks: Bbox[] = (ref.page_chunks ?? [])
    .map((c) => (c.bbox && isValidBbox(c.bbox) ? (c.bbox as Bbox) : null))
    .filter((b): b is Bbox => b != null)
    .sort((a, b) => a.y0 - b.y0);
  if (pageChunks.length === 0) return seeds;

  const seen = new Set<string>();
  const out: Bbox[] = [];
  const push = (b: Bbox): boolean => {
    const key = bboxDedupKey(b);
    if (seen.has(key)) return out.length < MAX_EXPANSION_BBOXES;
    seen.add(key);
    out.push(b);
    return out.length < MAX_EXPANSION_BBOXES;
  };

  for (const seed of seeds) {
    if (!push(seed)) break;
    let idx = pageChunks.findIndex((b) => bboxDedupKey(b) === bboxDedupKey(seed));
    if (idx < 0) {
      idx = pageChunks.findIndex(
        (b) => Math.abs(b.y0 - seed.y0) < 0.005 && Math.abs(b.x0 - seed.x0) < 0.05
      );
    }
    if (idx < 0) continue;
    let canGrow = out.length < MAX_EXPANSION_BBOXES;
    for (let i = idx + 1; canGrow && i < pageChunks.length; i++) {
      const prev = pageChunks[i - 1];
      const cur = pageChunks[i];
      if (cur.y0 - prev.y1 > NEIGHBOR_Y_GAP) break;
      canGrow = push(cur);
    }
    for (let i = idx - 1; canGrow && i >= 0; i--) {
      const next = pageChunks[i + 1];
      const cur = pageChunks[i];
      if (next.y0 - cur.y1 > NEIGHBOR_Y_GAP) break;
      canGrow = push(cur);
    }
    if (!canGrow) break;
  }
  return out;
}

/** Overlays to draw on a single PDF page. Bboxes are normalized to that page only. */
function overlaysForPage(
  page: number,
  highlights: ChatReference[],
  activeIndex?: number | null,
  activeRef?: ChatReference | null,
  documentId?: string | null
): ChatReference[] {
  if (activeRef?.page === page) {
    const multi = (activeRef.highlight_bboxes ?? []).filter(isValidBbox) as Bbox[];
    const seeds: Bbox[] = multi.length
      ? multi
      : isValidBbox(activeRef.bbox)
        ? [activeRef.bbox as Bbox]
        : [];
    if (!seeds.length) return [];

    const expanded = expandSeedBboxes(seeds, activeRef);
    const totalHeight = expanded.reduce((sum, b) => sum + (b.y1 - b.y0), 0);
    const bounded = totalHeight > MAX_PAGE_COVERAGE ? expanded.slice(0, 1) : expanded;
    const dedupe = dedupeByBboxOverlap as (
      items: ChatReference[],
      threshold?: number
    ) => ChatReference[];
    return dedupe(
      bounded.map((bbox) => ({ ...activeRef, bbox })),
      0.3
    );
  }

  // When a citation is actively focused, suppress passive overlays on other
  // pages — they otherwise flash as gray boxes on pages 1-2 while the viewer
  // is still scrolling to the active page, and create cross-document leaks.
  if (activeRef) return [];

  const expanded: ChatReference[] = [];
  for (const h of highlights) {
    if (documentId && h.document_id && h.document_id !== documentId) continue;
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

  const dedupe = dedupeByBboxOverlap as (
    items: ChatReference[],
    threshold?: number
  ) => ChatReference[];
  return dedupe(expanded, 0.3);
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
          activeRef,
          documentId
        );
        return overlays.map((h) => (
          <BboxOverlay
            key={`${h.chunk_id}-${bboxKey(h.bbox)}-${pageNumber}`}
            bbox={h.bbox as Bbox}
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
