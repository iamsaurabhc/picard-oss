"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { HelpCircle } from "lucide-react";
import { getPromptGuideSections } from "@/lib/unifiedChat/promptGuideContent";
import type { ComposerMode } from "@/lib/unifiedChatTypes";
import { cn } from "@/lib/utils";

type Props = {
  mode: ComposerMode;
  disabled?: boolean;
};

export function PromptGuideTip({ mode, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const sections = useMemo(() => getPromptGuideSections(mode), [mode]);

  useEffect(() => {
    const onClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div ref={ref} className="absolute right-3 top-3 z-10">
      <button
        ref={buttonRef}
        type="button"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        aria-label="Prompt writing guide"
        aria-expanded={open}
        title="How to write prompts for Picard"
        className={cn(
          "rounded-full p-1 text-neutral-400 transition-colors hover:bg-neutral-100 hover:text-neutral-600 focus:outline-none focus:ring-2 focus:ring-neutral-300",
          disabled && "pointer-events-none opacity-40"
        )}
      >
        <HelpCircle className="h-4 w-4" />
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="Prompt writing guide"
          className="absolute bottom-full right-0 z-50 mb-2 max-h-[360px] w-80 overflow-y-auto rounded-lg border border-neutral-200 bg-white py-3 shadow-lg"
        >
          <p className="px-3 pb-2 text-xs font-medium uppercase tracking-wide text-neutral-500">
            {mode === "review" ? "Review mode prompts" : "Ask mode prompts"}
          </p>
          <div className="space-y-3 px-3">
            {sections.map((section) => (
              <div key={section.title}>
                <h4 className="text-xs font-medium uppercase tracking-wide text-neutral-500">
                  {section.title}
                </h4>
                <p className="mt-1 text-sm text-neutral-700">{section.body}</p>
                {section.example ? (
                  <p className="mt-1.5 rounded bg-neutral-50 px-2 py-1 text-xs italic text-neutral-600">
                    {section.example}
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
