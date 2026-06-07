"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { TABULAR_TEMPLATES, type TabularTemplateId } from "@/lib/tabular/columnPresets";

type Props = {
  templateId: TabularTemplateId;
  onChange: (id: TabularTemplateId) => void;
  disabled?: boolean;
};

export function ReviewTemplatePill({ templateId, onChange, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const active = TABULAR_TEMPLATES.find((t) => t.id === templateId) ?? TABULAR_TEMPLATES[0];

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
        className={cn("composer-pill max-w-[180px]", disabled && "opacity-50")}
      >
        <span className="truncate">Template: {active.name}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-60" />
      </button>
      {open && (
        <div className="absolute bottom-full left-0 z-50 mb-2 max-h-60 w-64 overflow-y-auto rounded-lg border border-neutral-200 bg-white py-1 shadow-lg">
          {TABULAR_TEMPLATES.map((t) => (
            <button
              key={t.id}
              type="button"
              className="flex w-full items-start gap-2 px-3 py-2 text-left text-sm hover:bg-neutral-50"
              onClick={() => {
                onChange(t.id);
                setOpen(false);
              }}
            >
              <span className="flex-1">
                <span className="font-medium">{t.name}</span>
                <span className="mt-0.5 block text-xs text-neutral-500">{t.description}</span>
              </span>
              {t.id === templateId ? <Check className="mt-0.5 h-4 w-4 shrink-0" /> : null}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
