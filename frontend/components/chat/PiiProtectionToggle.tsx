"use client";

import React, { useEffect, useState } from "react";
import { Shield } from "lucide-react";
import { cn } from "@/lib/utils";

export const PII_STORAGE_KEY = "picard:enablePiiProtection";
export const PII_INFO_DISMISSED_KEY = "picard:piiInfoDismissed";

export function readPiiPreference(defaultOn: boolean): boolean {
  if (typeof window === "undefined") return defaultOn;
  const raw = localStorage.getItem(PII_STORAGE_KEY);
  if (raw === null) return defaultOn;
  return raw === "true";
}

export function writePiiPreference(enabled: boolean): void {
  localStorage.setItem(PII_STORAGE_KEY, enabled ? "true" : "false");
}

type Props = {
  llmProvider: string;
  defaultEnabled?: boolean;
  disabled?: boolean;
  enabled: boolean;
  onChange: (enabled: boolean) => void;
};

export function PiiProtectionToggle({
  llmProvider,
  defaultEnabled = true,
  disabled = false,
  enabled,
  onChange,
}: Props) {
  const [showInfo, setShowInfo] = useState(false);
  const isOllama = llmProvider === "ollama";
  const effectiveDisabled = disabled || isOllama;

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (localStorage.getItem(PII_STORAGE_KEY) === null) {
      writePiiPreference(defaultEnabled && !isOllama);
      onChange(defaultEnabled && !isOllama);
    }
  }, [defaultEnabled, isOllama, onChange]);

  const tooltip = isOllama
    ? "Not needed — your LLM runs locally on your machine."
    : "Mask names, emails, phones, and IDs before sending to cloud LLMs; restore them in answers. Helps with GDPR, DPDPA, and client confidentiality.";

  const active = enabled && !isOllama;

  return (
    <div
      className={cn(
        "group relative flex items-center gap-1.5 rounded-md border px-2 py-1 shadow-sm",
        active
          ? "border-blue-200/80 bg-blue-50/70"
          : "border-neutral-200/80 bg-neutral-50/80",
        effectiveDisabled && "opacity-70"
      )}
    >
      <button
        type="button"
        className={cn(
          "rounded p-1 hover:bg-white/80 hover:text-neutral-800",
          active ? "text-blue-700" : "text-neutral-500"
        )}
        aria-label="PII protection info"
        aria-describedby="pii-shield-tooltip"
        onClick={() => setShowInfo((v) => !v)}
      >
        <Shield className="h-4 w-4" />
      </button>
      <label
        className={cn(
          "flex cursor-pointer items-center gap-1.5 text-xs",
          active ? "text-blue-900" : "text-neutral-600",
          effectiveDisabled && "cursor-not-allowed"
        )}
      >
        <input
          type="checkbox"
          checked={active}
          disabled={effectiveDisabled}
          onChange={(e) => {
            const next = e.target.checked;
            writePiiPreference(next);
            onChange(next);
          }}
        />
        <span>PII shield</span>
      </label>
      <div
        id="pii-shield-tooltip"
        role="tooltip"
        className="pointer-events-none absolute right-0 top-full z-40 mt-1.5 hidden w-72 max-w-[calc(100vw-2rem)] rounded-md border border-neutral-200 bg-white p-3 text-xs leading-relaxed text-neutral-700 shadow-md group-hover:block group-focus-within:block"
      >
        {tooltip}
      </div>
      {showInfo && !isOllama ? (
        <div className="absolute right-0 top-full z-30 mt-1 w-80 max-w-[calc(100vw-2rem)] rounded-md border border-neutral-200 bg-white p-3 text-xs leading-relaxed text-neutral-700 shadow-md">
          <p className="font-medium text-neutral-900">Private data protection</p>
          <p className="mt-1">
            Before your question and document excerpts reach OpenAI or Anthropic, Picard replaces
            personal identifiers with temporary tokens locally. Answers are restored on your machine.
            Raw identifiers are not stored in the PII map or sent to the provider.
          </p>
          <button
            type="button"
            className="mt-2 text-neutral-500 underline"
            onClick={() => setShowInfo(false)}
          >
            Close
          </button>
        </div>
      ) : null}
    </div>
  );
}

type BannerProps = {
  visible: boolean;
  onDismiss: () => void;
};

export function PiiInfoBanner({ visible, onDismiss }: BannerProps) {
  if (!visible) return null;
  return (
    <div className="mb-3 flex items-start justify-between gap-3 rounded-lg border border-blue-100 bg-blue-50 px-3 py-2 text-xs text-blue-900">
      <p>
        <strong>PII shield is on.</strong> Names, emails, and phone numbers are masked before cloud
        LLM calls and restored in your answers. Toggle off in the header if you need the model to see
        raw text (local Ollama skips this automatically).
      </p>
      <button type="button" className="shrink-0 underline" onClick={onDismiss}>
        Dismiss
      </button>
    </div>
  );
}
