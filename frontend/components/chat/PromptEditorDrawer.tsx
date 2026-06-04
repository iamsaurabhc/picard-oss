"use client";

import { useEffect, useState } from "react";
import { picardApi } from "@/lib/picardApi";

const PHASE_TO_PROMPT: Record<string, string> = {
  understanding: "query_understanding",
  rank: "context_ranker",
  generate: "query_understanding",
};

type Props = {
  phase: string;
  onClose: () => void;
};

export function PromptEditorDrawer({ phase, onClose }: Props) {
  const promptKey = PHASE_TO_PROMPT[phase];
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!promptKey) return;
    setLoading(true);
    picardApi
      .getPrompt(promptKey)
      .then((p) => setText(p.text))
      .finally(() => setLoading(false));
  }, [promptKey]);

  if (!promptKey) return null;

  return (
    <div className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-neutral-200 bg-white shadow-xl">
      <div className="flex items-center justify-between border-b border-neutral-200 px-4 py-3">
        <h3 className="text-sm font-medium">Prompt: {promptKey}</h3>
        <button type="button" className="text-sm text-neutral-500 hover:text-neutral-800" onClick={onClose}>
          Close
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <p className="text-sm text-neutral-500">Loading…</p>
        ) : (
          <textarea
            className="h-64 w-full rounded border border-neutral-300 p-2 font-mono text-xs"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        )}
      </div>
      <div className="flex gap-2 border-t border-neutral-200 p-4">
        <button
          type="button"
          className="rounded bg-neutral-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
          disabled={saving}
          onClick={async () => {
            setSaving(true);
            await picardApi.updatePrompt(promptKey, text);
            setSaving(false);
            onClose();
          }}
        >
          Save
        </button>
        <button
          type="button"
          className="rounded border border-neutral-300 px-3 py-1.5 text-sm"
          onClick={async () => {
            const p = await picardApi.resetPrompt(promptKey);
            setText(p.text);
          }}
        >
          Reset default
        </button>
      </div>
    </div>
  );
}
