"use client";

import type { ToolStep } from "./useAgentActivity";

type Props = {
  steps: ToolStep[];
};

export function ToolTimeline({ steps }: Props) {
  if (!steps.length) return null;
  return (
    <div className="space-y-1 text-xs text-neutral-600">
      <p className="font-medium text-neutral-800">Tool activity</p>
      <ol className="space-y-1">
        {steps.map((s) => (
          <li key={s.id} className="rounded border border-neutral-200 bg-neutral-50 px-2 py-1">
            <span className="font-mono">{s.tool}</span>
            <span
              className={
                s.status === "refused"
                  ? " ml-2 text-amber-700"
                  : s.status === "done"
                    ? " ml-2 text-green-700"
                    : " ml-2 text-neutral-500"
              }
            >
              {s.status}
            </span>
            {s.detail && <p className="mt-0.5 truncate text-neutral-500">{s.detail}</p>}
          </li>
        ))}
      </ol>
    </div>
  );
}
