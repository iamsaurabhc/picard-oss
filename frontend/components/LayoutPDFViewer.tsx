"use client";

import { useEffect, useMemo, useRef } from "react";
import { BboxOverlay } from "@/components/pdf/BboxOverlay";
import { isValidBbox } from "@/components/pdf/bbox-utils";
import { CHUNK_TYPE_STYLES } from "@/components/pdf/chunk-styles";
import { PdfPageViewer, type PdfPageViewerHandle } from "@/components/pdf/PdfPageViewer";
import { cn } from "@/lib/utils";
import type { ChunkRecord } from "@/lib/picardApi";

type Props = {
  documentId: string;
  page: number;
  onPageChange: (page: number) => void;
  chunks: ChunkRecord[];
  selectedChunkId: string | null;
  showAllBlocks: boolean;
};

export function LayoutPDFViewer({
  documentId,
  page,
  onPageChange,
  chunks,
  selectedChunkId,
  showAllBlocks,
}: Props) {
  const viewerRef = useRef<PdfPageViewerHandle>(null);

  useEffect(() => {
    if (!selectedChunkId) return;
    const chunk = chunks.find((c) => c.id === selectedChunkId);
    if (!chunk || !isValidBbox(chunk.bbox)) return;
    requestAnimationFrame(() => {
      viewerRef.current?.scrollToPage(chunk.page_number, chunk.bbox.y0);
    });
  }, [selectedChunkId, chunks]);

  const chunksByPage = useMemo(() => {
    const map = new Map<number, ChunkRecord[]>();
    for (const chunk of chunks) {
      const p = chunk.page_number;
      const list = map.get(p) ?? [];
      list.push(chunk);
      map.set(p, list);
    }
    return map;
  }, [chunks]);

  const visibleOnPage = (pageNumber: number) => {
    const pageChunks = chunksByPage.get(pageNumber) ?? [];
    if (showAllBlocks) return pageChunks;
    return pageChunks.filter((c) => c.id === selectedChunkId);
  };

  const blocksOnCurrentPage = visibleOnPage(page).length;

  return (
    <PdfPageViewer
      ref={viewerRef}
      documentId={documentId}
      page={page}
      onPageChange={onPageChange}
      scrollMode="continuous"
      toolbarExtra={
        <span className="ml-auto text-xs text-neutral-500">
          {blocksOnCurrentPage} block{blocksOnCurrentPage === 1 ? "" : "s"} on page
        </span>
      }
    >
      {({ pageWidth, pageHeight, pageNumber }) =>
        visibleOnPage(pageNumber).map((chunk) => {
          if (!isValidBbox(chunk.bbox)) return null;
          const styles = CHUNK_TYPE_STYLES[chunk.chunk_type];
          const active = chunk.id === selectedChunkId;
          const preview =
            chunk.text_content.length > 40
              ? `${chunk.text_content.slice(0, 40)}…`
              : chunk.text_content;
          return (
            <BboxOverlay
              key={chunk.id}
              bbox={chunk.bbox}
              width={pageWidth}
              height={pageHeight}
              active={active}
              label={active ? `${chunk.chunk_type}: ${preview}` : undefined}
              className={cn(styles.border, styles.bg, active && "ring-amber-500")}
            />
          );
        })
      }
    </PdfPageViewer>
  );
}
