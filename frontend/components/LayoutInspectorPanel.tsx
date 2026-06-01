"use client";

import { DocumentParseInfo } from "@/components/DocumentParseInfo";
import { CHUNK_TYPE_STYLES } from "@/components/pdf/chunk-styles";
import { cn } from "@/lib/utils";
import type { ChunkRecord, DocumentRecord } from "@/lib/picardApi";

type Props = {
  document: DocumentRecord;
  page: number;
  chunks: ChunkRecord[];
  selectedChunkId: string | null;
  onSelectChunk: (chunkId: string) => void;
  showAllBlocks: boolean;
  onShowAllBlocksChange: (show: boolean) => void;
};

function truncate(text: string, max = 120): string {
  if (text.length <= max) return text;
  return `${text.slice(0, max)}…`;
}

export function LayoutInspectorPanel({
  document,
  page,
  chunks,
  selectedChunkId,
  onSelectChunk,
  showAllBlocks,
  onShowAllBlocksChange,
}: Props) {
  const isParsing = document.parse_status === "pending" || document.parse_status === "parsing";
  const isError = document.parse_status === "error";

  return (
    <div className="flex h-full flex-col overflow-hidden border-l border-neutral-200 bg-white">
      <div className="border-b border-neutral-200 px-4 py-3">
        <h2 className="truncate text-sm font-semibold text-neutral-900">{document.file_name}</h2>
        <div className="mt-2">
          <DocumentParseInfo textSource={document.text_source} ocrEngine={document.ocr_engine} />
        </div>
        <p className="mt-2 text-xs text-neutral-500">
          Page {page}
          {document.page_count ? ` / ${document.page_count}` : ""}
          {" · "}
          {chunks.length} block{chunks.length === 1 ? "" : "s"}
        </p>
        <label className="mt-3 flex cursor-pointer items-center gap-2 text-xs text-neutral-700">
          <input
            type="checkbox"
            checked={showAllBlocks}
            onChange={(e) => onShowAllBlocksChange(e.target.checked)}
            className="rounded border-neutral-300"
          />
          Show all blocks on page
        </label>
      </div>

      <div className="border-b border-neutral-100 px-4 py-2">
        <p className="mb-1 text-xs font-medium text-neutral-600">Block types</p>
        <div className="flex flex-wrap gap-2">
          {(Object.keys(CHUNK_TYPE_STYLES) as ChunkRecord["chunk_type"][]).map((type) => (
            <span
              key={type}
              className={cn(
                "rounded px-2 py-0.5 text-[10px] font-medium capitalize",
                CHUNK_TYPE_STYLES[type].badge
              )}
            >
              {type}
            </span>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {isParsing ? (
          <p className="px-4 py-6 text-sm text-neutral-500">Document is still parsing…</p>
        ) : isError ? (
          <p className="px-4 py-6 text-sm text-red-600">
            Parse failed{document.parse_error ? `: ${document.parse_error}` : "."}
          </p>
        ) : chunks.length === 0 ? (
          <p className="px-4 py-6 text-sm text-neutral-500">No layout blocks on this page.</p>
        ) : (
          <ul className="divide-y divide-neutral-100">
            {chunks.map((chunk) => {
              const styles = CHUNK_TYPE_STYLES[chunk.chunk_type];
              const selected = chunk.id === selectedChunkId;
              return (
                <li key={chunk.id}>
                  <button
                    type="button"
                    onClick={() => onSelectChunk(chunk.id)}
                    className={cn(
                      "w-full px-4 py-3 text-left transition-colors hover:bg-neutral-50",
                      selected && "bg-amber-50"
                    )}
                  >
                    <div className="mb-1 flex items-center gap-2">
                      <span
                        className={cn(
                          "rounded px-1.5 py-0.5 text-[10px] font-medium capitalize",
                          styles.badge
                        )}
                      >
                        {chunk.chunk_type}
                      </span>
                      {chunk.token_count != null ? (
                        <span className="text-[10px] text-neutral-400">{chunk.token_count} tokens</span>
                      ) : null}
                    </div>
                    {chunk.heading_path ? (
                      <p className="mb-1 text-[11px] text-neutral-500">{chunk.heading_path}</p>
                    ) : null}
                    <p className="text-xs leading-relaxed text-neutral-800">
                      {truncate(chunk.text_content)}
                    </p>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
