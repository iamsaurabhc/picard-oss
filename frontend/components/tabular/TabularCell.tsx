"use client";

import { Expand, Loader2 } from "lucide-react";
import type { TabularCell as TCell, TabularColumn } from "@/lib/picardApi";
import { preprocessCitations } from "./citation-utils";

const FLAG_STYLES = {
  green: "bg-green-500",
  grey: "bg-gray-400",
  yellow: "bg-amber-400",
  red: "bg-red-500",
} as const;

type Props = {
  cell: TCell;
  column?: TabularColumn;
  onExpand: () => void;
  onCitationClick?: (page: number, quote: string) => void;
  highlighted?: boolean;
};

export function TabularCellComponent({ cell, column, onExpand, onCitationClick, highlighted }: Props) {
  if (cell.status === "pending") {
    return (
      <div className="flex h-full min-h-[48px] items-center px-3 text-xs text-neutral-400">Pending</div>
    );
  }
  if (cell.status === "generating") {
    return (
      <div className="flex h-full min-h-[48px] items-center gap-2 px-3 text-xs text-neutral-500">
        <Loader2 className="h-3 w-3 animate-spin" />
        Generating…
      </div>
    );
  }
  if (cell.status === "error") {
    return (
      <div className="flex h-full min-h-[48px] items-center px-3 text-xs text-red-600">
        {cell.summary || "Error"}
      </div>
    );
  }

  const summary = cell.summary || "";
  const { citations } = preprocessCitations(summary);
  const preview = summary.replace(/\[\[[^\]]+\]\]/g, "").slice(0, 200);
  const flag = cell.flag && cell.flag in FLAG_STYLES ? cell.flag : "grey";

  return (
    <div
      className={`group relative flex h-full min-h-[48px] cursor-pointer flex-col px-3 py-2 hover:bg-neutral-50 ${
        highlighted ? "ring-2 ring-blue-400 ring-inset" : ""
      }`}
      onClick={onExpand}
    >
      <div className="mb-1 flex items-center gap-2">
        <span className={`h-2 w-2 shrink-0 rounded-full ${FLAG_STYLES[flag]}`} title={flag} />
        {citations.length > 0 ? (
          <button
            type="button"
            className="text-[10px] text-blue-600 hover:underline"
            onClick={(e) => {
              e.stopPropagation();
              onCitationClick?.(citations[0].page, citations[0].quote);
            }}
          >
            p.{citations[0].page}
          </button>
        ) : null}
        <button
          type="button"
          className="ml-auto opacity-0 group-hover:opacity-100"
          onClick={(e) => {
            e.stopPropagation();
            onExpand();
          }}
        >
          <Expand className="h-3.5 w-3.5 text-neutral-400" />
        </button>
      </div>
      <p className="line-clamp-3 text-xs leading-relaxed text-neutral-800">{preview}</p>
      {column?.format === "yes_no" && summary ? (
        <span className="mt-1 inline-block rounded bg-neutral-100 px-1.5 py-0.5 text-[10px]">
          {summary.slice(0, 40)}
        </span>
      ) : null}
    </div>
  );
}
