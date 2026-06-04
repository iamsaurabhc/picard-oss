"use client";

import { useState } from "react";
import type { ActivityPhaseStep } from "./useRetrievalActivity";
import { PromptEditorDrawer } from "./PromptEditorDrawer";

const EDITABLE_PHASES = new Set(["understanding", "rank"]);

type Props = {
  step: ActivityPhaseStep;
  showConnector?: boolean;
};

export function RetrievalPhaseRow({ step, showConnector }: Props) {
  const [showPrompt, setShowPrompt] = useState(false);
  const canEdit = EDITABLE_PHASES.has(step.phase) && step.status === "done";

  return (
    <>
      <div className="relative flex items-start text-sm text-neutral-600">
        {showConnector && (
          <div className="absolute bottom-0 left-[2.5px] top-[13px] h-[calc(100%+11px)] w-px bg-neutral-300" />
        )}
        {step.status === "active" ? (
          <div className="mt-2 h-1.5 w-1.5 shrink-0 animate-spin rounded-full border border-neutral-400 border-t-transparent" />
        ) : (
          <div className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" />
        )}
        <div className="ml-2 min-w-0 flex-1 whitespace-normal break-words">
          <span className="font-medium text-neutral-700">{step.label}</span>
          {canEdit && (
            <button
              type="button"
              className="ml-2 text-xs text-neutral-500 underline hover:text-neutral-800"
              onClick={() => setShowPrompt(true)}
            >
              Edit prompt
            </button>
          )}
        </div>
      </div>
      {showPrompt && (
        <PromptEditorDrawer phase={step.phase} onClose={() => setShowPrompt(false)} />
      )}
    </>
  );
}
