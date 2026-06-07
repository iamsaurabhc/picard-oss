"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

export type DocumentOption = {
  id: string;
  file_name: string;
};

type Props = {
  documents: DocumentOption[];
  selectedIds: string[];
  onChange: (ids: string[]) => void;
  openRequested?: boolean;
  onOpenHandled?: () => void;
  disabled?: boolean;
};

export function DocumentScopePill({
  documents,
  selectedIds,
  onChange,
  openRequested,
  onOpenHandled,
  disabled,
}: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (openRequested) {
      setOpen(true);
      onOpenHandled?.();
    }
  }, [openRequested, onOpenHandled]);

  useEffect(() => {
    const onClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
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
        : `${selectedIds.length} documents`;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className={cn("composer-pill max-w-[200px]", disabled && "opacity-50")}
      >
        <span className="truncate">Documents: {label}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-60" />
      </button>
      {open && (
        <div className="absolute bottom-full left-0 z-50 mb-2 max-h-60 w-72 overflow-y-auto rounded-lg border border-neutral-200 bg-white py-1 shadow-lg">
          <div className="flex items-center justify-between border-b border-neutral-100 px-3 py-2">
            <span className="text-xs text-neutral-500">Scope</span>
            {selectedIds.length > 0 && (
              <button
                type="button"
                className="text-xs text-neutral-500 hover:text-neutral-800"
                onClick={() => onChange([])}
              >
                Clear
              </button>
            )}
          </div>
          {documents.length === 0 ? (
            <p className="px-3 py-2 text-sm text-neutral-500">No documents indexed yet</p>
          ) : (
            documents.map((d) => (
              <label
                key={d.id}
                className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-neutral-50"
              >
                <input
                  type="checkbox"
                  checked={selectedIds.includes(d.id)}
                  onChange={() => toggle(d.id)}
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
