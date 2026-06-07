"use client";

import { useEffect, useRef, useState } from "react";
import { FileUp, FolderOpen, Plus } from "lucide-react";
import { cn } from "@/lib/utils";

type Props = {
  onUpload: (files: FileList | File[]) => void;
  onBrowseVault?: () => void;
  disabled?: boolean;
  uploadRequestId?: number;
};

export function AddContextMenu({ onUpload, onBrowseVault, disabled, uploadRequestId }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (uploadRequestId) inputRef.current?.click();
  }, [uploadRequestId]);

  useEffect(() => {
    const onClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "composer-pill flex h-8 w-8 items-center justify-center rounded-full p-0",
          disabled && "opacity-50"
        )}
        aria-label="Add context"
        title="Add context"
      >
        <Plus className="h-4 w-4" />
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,application/pdf"
        multiple
        className="hidden"
        onChange={(e) => {
          const files = e.target.files;
          if (files?.length) onUpload(files);
          e.target.value = "";
          setOpen(false);
        }}
      />
      {open && (
        <div className="absolute bottom-full left-0 z-50 mb-2 w-48 rounded-lg border border-neutral-200 bg-white py-1 shadow-lg">
          <p className="px-3 py-1.5 text-xs text-neutral-500">Add Context</p>
          <button
            type="button"
            className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-neutral-50"
            onClick={() => inputRef.current?.click()}
          >
            <FileUp className="h-4 w-4 text-neutral-500" />
            Upload documents
          </button>
          {onBrowseVault ? (
            <button
              type="button"
              className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-neutral-50"
              onClick={() => {
                onBrowseVault();
                setOpen(false);
              }}
            >
              <FolderOpen className="h-4 w-4 text-neutral-500" />
              From vault
            </button>
          ) : null}
        </div>
      )}
    </div>
  );
}

export function openUploadPicker(inputRef: React.RefObject<HTMLInputElement | null>) {
  inputRef.current?.click();
}
