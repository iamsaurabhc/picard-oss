"use client";

import { cn } from "@/lib/utils";

type Props = {
  mode: "rag" | "agent";
  disabled?: boolean;
  onChange: (mode: "rag" | "agent") => void;
};

export function ModeToggle({ mode, disabled, onChange }: Props) {
  return (
    <div className="inline-flex rounded border border-neutral-300 p-0.5 text-xs">
      <button
        type="button"
        disabled={disabled}
        className={cn(
          "rounded px-2 py-1",
          mode === "rag" ? "bg-neutral-900 text-white" : "text-neutral-600 hover:bg-neutral-100"
        )}
        onClick={() => onChange("rag")}
      >
        Chat
      </button>
      <button
        type="button"
        disabled={disabled}
        className={cn(
          "rounded px-2 py-1",
          mode === "agent" ? "bg-neutral-900 text-white" : "text-neutral-600 hover:bg-neutral-100"
        )}
        onClick={() => onChange("agent")}
      >
        Agent
      </button>
    </div>
  );
}
