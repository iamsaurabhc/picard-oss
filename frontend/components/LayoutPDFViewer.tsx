"use client";

import { BboxOverlay } from "@/components/pdf/BboxOverlay";
import { isValidBbox } from "@/components/pdf/bbox-utils";
import { CHUNK_TYPE_STYLES } from "@/components/pdf/chunk-styles";
import { PdfPageViewer } from "@/components/pdf/PdfPageViewer";
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
  const visibleChunks = showAllBlocks
    ? chunks
    : chunks.filter((c) => c.id === selectedChunkId);

  return (
    <PdfPageViewer
      documentId={documentId}
      page={page}
      onPageChange={onPageChange}
      toolbarExtra={
        <span className="ml-auto text-xs text-neutral-500">
          {visibleChunks.length} block{visibleChunks.length === 1 ? "" : "s"} on page
        </span>
      }
    >
      {({ pageWidth, pageHeight }) =>
        visibleChunks.map((chunk) => {
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
              className={cn(
                styles.border,
                styles.bg,
                active && "ring-amber-500"
              )}
            />
          );
        })
      }
    </PdfPageViewer>
  );
}
