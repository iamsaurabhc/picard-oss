"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, MessageSquare, Table2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ComposerMode } from "@/lib/unifiedChatTypes";

const MODES: { id: ComposerMode; label: string; icon: typeof MessageSquare }[] = [
  { id: "ask", label: "Ask", icon: MessageSquare },
  { id: "review", label: "Review", icon: Table2 },
];

type Props = {
  mode: ComposerMode;
  onChange: (mode: ComposerMode) => void;
  disabled?: boolean;
};

export function ModeSelectorPill({ mode, onChange, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const active = MODES.find((m) => m.id === mode) ?? MODES[0];
  const Icon = active.icon;

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
        data-active="true"
        onClick={() => setOpen((o) => !o)}
        className={cn("composer-pill", disabled && "opacity-50")}
      >
        <Icon className="h-3.5 w-3.5" />
        <span>{active.label}</span>
        <ChevronDown className="h-3.5 w-3.5 opacity-60" />
      </button>
      {open && (
        <div className="absolute bottom-full left-0 z-50 mb-2 min-w-[140px] rounded-lg border border-neutral-200 bg-white py-1 shadow-lg">
          {MODES.map((m) => {
            const MIcon = m.icon;
            return (
              <button
                key={m.id}
                type="button"
                className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-neutral-50"
                onClick={() => {
                  onChange(m.id);
                  setOpen(false);
                }}
              >
                <MIcon className="h-4 w-4 text-neutral-500" />
                <span className="flex-1 text-left">{m.label}</span>
                {m.id === mode ? <Check className="h-4 w-4" /> : null}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
