"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import type { ActivityStep } from "./useRetrievalActivity";
import type { RetrievalSummary } from "./useRetrievalActivity";
import { RetrievalPhaseRow } from "./RetrievalPhaseRow";
import { RetrievalSnippetRow } from "./RetrievalSnippetRow";

type Props = {
  steps: ActivityStep[];
  stepCount: number;
  isStreaming: boolean;
  shouldMinimize: boolean;
  retrievalSummary?: RetrievalSummary | null;
  compact?: boolean;
};

export function RetrievalActivityPanel({
  steps,
  stepCount,
  isStreaming,
  shouldMinimize,
  retrievalSummary,
  compact = false,
}: Props) {
  const [userToggled, setUserToggled] = useState(false);
  const [isOpen, setIsOpen] = useState(true);
  const hasMinimizedRef = useRef(shouldMinimize);

  useEffect(() => {
    if (shouldMinimize) hasMinimizedRef.current = true;
    if (userToggled) return;
    setIsOpen(!shouldMinimize && !hasMinimizedRef.current);
  }, [shouldMinimize, userToggled]);

  const stepWord = `step${stepCount === 1 ? "" : "s"}`;
  let label = isStreaming ? "Working" : `Completed in ${stepCount} ${stepWord}`;
  if (retrievalSummary && !isStreaming) {
    const parts = [`${retrievalSummary.chunk_count} chunk${retrievalSummary.chunk_count === 1 ? "" : "s"}`];
    if (retrievalSummary.bundle_count > 0) {
      parts.push(`${retrievalSummary.bundle_count} bundle${retrievalSummary.bundle_count === 1 ? "" : "s"}`);
    }
    parts.push(retrievalSummary.mode.toLowerCase());
    label = `Retrieved ${parts.join(" · ")}`;
  }

  const buttonTextClass = compact ? "text-xs" : "text-sm";
  const childrenGapClass = compact ? "gap-2.5" : "gap-3";

  return (
    <div className="rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-2">
      <button
        type="button"
        onClick={() => {
          setUserToggled(true);
          setIsOpen((v) => !v);
        }}
        className={`flex w-full items-center justify-between font-serif text-neutral-500 transition-colors hover:text-neutral-700 ${buttonTextClass}`}
      >
        <span className="flex min-w-0 items-baseline">
          <span className="truncate">{label}</span>
          {isStreaming && (
            <span className="ml-1 inline-flex shrink-0 items-baseline">
              <span className="mr-0.5 h-0.5 w-0.5 animate-[bounce_1.4s_infinite_0s] rounded-full bg-neutral-400" />
              <span className="mr-0.5 h-0.5 w-0.5 animate-[bounce_1.4s_infinite_0.2s] rounded-full bg-neutral-400" />
              <span className="h-0.5 w-0.5 animate-[bounce_1.4s_infinite_0.4s] rounded-full bg-neutral-400" />
            </span>
          )}
        </span>
        <ChevronDown
          size={12}
          className={`ml-2 shrink-0 transition-transform duration-200 ${isOpen ? "" : "-rotate-90"}`}
        />
      </button>
      {isOpen && (
        <div className={`mt-3 flex flex-col ${childrenGapClass}`}>
          {steps.length === 0 && isStreaming ? (
            <div className="flex items-start text-sm text-neutral-500">
              <div className="mt-2 h-1.5 w-1.5 shrink-0 animate-spin rounded-full border border-neutral-400 border-t-transparent" />
              <span className="ml-2">Starting retrieval…</span>
            </div>
          ) : null}
          {steps.map((step, index) => {
            const showConnector = index < steps.length - 1;
            if (step.kind === "phase") {
              return (
                <RetrievalPhaseRow key={step.id} step={step} showConnector={showConnector} />
              );
            }
            return (
              <RetrievalSnippetRow key={step.id} step={step} showConnector={showConnector} />
            );
          })}
        </div>
      )}
    </div>
  );
}
