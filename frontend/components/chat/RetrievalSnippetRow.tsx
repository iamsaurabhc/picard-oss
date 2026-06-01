"use client";

import type { ActivitySnippetStep } from "./useRetrievalActivity";

type Props = {
  step: ActivitySnippetStep;
  showConnector?: boolean;
};

export function RetrievalSnippetRow({ step, showConnector }: Props) {
  return (
    <div className="relative flex items-start text-sm text-neutral-600">
      {showConnector && (
        <div className="absolute bottom-0 left-[2.5px] top-[13px] h-[calc(100%+11px)] w-px bg-neutral-300" />
      )}
      <div className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-neutral-300" />
      <div className="ml-2 min-w-0 flex-1 whitespace-normal break-words">
        <div className="text-xs text-neutral-500">
          <span className="font-medium text-neutral-600">{step.document_name}</span>
          {" · "}
          p.{step.page_number}
        </div>
        <p className="mt-0.5 line-clamp-2 text-neutral-700">{step.text}</p>
      </div>
    </div>
  );
}
