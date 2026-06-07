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

  return (
    <div className="relative flex items-center gap-1.5">
      <button
        type="button"
        className="rounded p-1 text-neutral-500 hover:bg-neutral-100 hover:text-neutral-800"
        title={tooltip}
        aria-label="PII protection info"
        onClick={() => setShowInfo((v) => !v)}
      >
        <Shield className="h-4 w-4" />
      </button>
      <label
        className={cn(
          "flex cursor-pointer items-center gap-1.5 text-xs text-neutral-600",
          effectiveDisabled && "cursor-not-allowed opacity-60"
        )}
        title={tooltip}
      >
        <input
          type="checkbox"
          checked={enabled && !isOllama}
          disabled={effectiveDisabled}
          onChange={(e) => {
            const next = e.target.checked;
            writePiiPreference(next);
            onChange(next);
          }}
        />
        <span>PII shield</span>
      </label>
      {showInfo && !isOllama ? (
        <div className="absolute left-0 top-full z-30 mt-1 max-w-xs rounded border border-neutral-200 bg-white p-3 text-xs text-neutral-700 shadow-md">
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
