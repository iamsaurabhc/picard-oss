"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

export type DocumentOption = {
  id: string;
  file_name: string;
};

type Props = {
  documents: DocumentOption[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
  className?: string;
};

export function DocumentMultiSelect({ documents, selectedIds, onChange, className }: Props) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const toggle = (id: string) => {
    if (selectedIds.includes(id)) {
      onChange(selectedIds.filter((x) => x !== id));
    } else {
      onChange([...selectedIds, id]);
    }
  };

  const label =
    selectedIds.length === 0
      ? "All documents"
      : selectedIds.length === 1
        ? documents.find((d) => d.id === selectedIds[0])?.file_name ?? "1 document"
        : `${selectedIds.length} documents selected`;

  const selectedDocs = documents.filter((d) => selectedIds.includes(d.id));

  return (
    <div ref={containerRef} className={cn("relative min-w-0 flex-1", className)}>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex h-9 min-w-0 max-w-xs flex-1 items-center truncate rounded-md border border-neutral-300 bg-white px-3 text-left text-sm hover:bg-neutral-50"
        >
          <span className="truncate">{label}</span>
        </button>
        {selectedIds.length > 0 && (
          <button
            type="button"
            onClick={() => onChange([])}
            className="shrink-0 text-xs text-neutral-500 hover:text-neutral-800"
          >
            Clear
          </button>
        )}
      </div>

      {selectedDocs.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {selectedDocs.map((d) => (
            <span
              key={d.id}
              className="inline-flex max-w-[200px] items-center gap-1 truncate rounded-full bg-neutral-100 px-2 py-0.5 text-xs text-neutral-700"
              title={d.file_name}
            >
              <span className="truncate">{d.file_name}</span>
              <button
                type="button"
                className="shrink-0 text-neutral-400 hover:text-neutral-700"
                onClick={() => toggle(d.id)}
                aria-label={`Remove ${d.file_name}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      {open && (
        <div className="absolute left-0 z-50 mt-1 max-h-60 w-72 overflow-y-auto rounded-md border border-neutral-200 bg-white py-1 shadow-lg">
          {documents.length === 0 ? (
            <p className="px-3 py-2 text-sm text-neutral-500">No documents</p>
          ) : (
            documents.map((d) => (
              <label
                key={d.id}
                className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-neutral-50"
                title={d.file_name}
              >
                <input
                  type="checkbox"
                  checked={selectedIds.includes(d.id)}
                  onChange={() => toggle(d.id)}
                  className="shrink-0"
                />
                <span className="truncate">{d.file_name}</span>
              </label>
            ))
          )}
        </div>
      )}
    </div>
  );
}